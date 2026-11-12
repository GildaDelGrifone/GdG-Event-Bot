"""Permanent deletion of a cancelled event: Eventbrite, public Telegram messages, image files and database rows.

The admin-chat messages (the card, story previews, notices) are left alone on purpose.
"""
import asyncio
import logging
from dataclasses import dataclass, field

from telegram.error import TelegramError

from core import config
from core.db import delete_event, image_path_in_use
from core.eventbrite import delete_eventbrite_event, eventbrite_enabled
from core.eventbrite.media import short_reason
from utils.night_images import delete_event_images
from utils.templates.approval import LEFTOVER_CHANNEL_POST, LEFTOVER_DISCUSSION_REPLY
from bot.service.eventbrite import is_gone
from bot.service.notices import discussion_chat_id
from bot.service.posts import _execute_with_retry

logger = logging.getLogger(__name__)

EVENTBRITE_NOT_CONFIGURED = "integrazione Eventbrite non configurata"


@dataclass
class DeletionResult:
    eventbrite_error: str | None = None  # set when Eventbrite refused: nothing else was touched
    leftovers: list = field(default_factory=list)  # (description, link or None) of public messages still there
    db_failed: bool = False  # the rows could not be deleted (logged by db_safe); the event is still in the database

    @property
    def deleted(self):
        return self.eventbrite_error is None


def _message_gone(error):
    text = str(error).lower()
    return "message to delete not found" in text or "message_id_invalid" in text


async def _delete_message(bot, chat_id, message_id, label, event_id):
    """True when the message is gone (deleted now, or already missing)."""
    try:
        await _execute_with_retry(lambda: bot.delete_message(chat_id=chat_id, message_id=int(message_id)))
        logger.info(f"Deleted the {label} of event #{event_id} (chat {chat_id}, message {message_id}).")
        return True
    except TelegramError as e:
        if _message_gone(e):
            logger.info(f"The {label} of event #{event_id} was already gone.")
            return True
        logger.warning(f"Could not delete the {label} of event #{event_id}: {e}")
        return False


async def _delete_on_eventbrite(event):
    """None when the event is no longer on Eventbrite, else a short reason why it is still there."""
    eb_id = event.get('eventbrite_event_id')
    if not eb_id:
        return None
    if not eventbrite_enabled():
        return EVENTBRITE_NOT_CONFIGURED
    try:
        await asyncio.to_thread(delete_eventbrite_event, eb_id)
        logger.info(f"Deleted Eventbrite event {eb_id} of event #{event['id']}.")
    except Exception as e:
        if is_gone(e):
            logger.info(f"Eventbrite event {eb_id} of event #{event['id']} was already deleted.")
            return None
        logger.warning(f"Eventbrite refused to delete event {eb_id} of #{event['id']}: {e}")
        return short_reason(getattr(e, 'description', None) or str(e)) or type(e).__name__
    return None


async def _delete_public_messages(bot, event):
    leftovers = []
    if event.get('telegram_message_id') and config.PUBLIC_CHANNEL_ID:
        if not await _delete_message(bot, config.PUBLIC_CHANNEL_ID, event['telegram_message_id'],
                                     "channel post", event['id']):
            leftovers.append((LEFTOVER_CHANNEL_POST, event.get('message_link')))
    disc_chat = event.get('discussion_chat_id') or discussion_chat_id()
    if event.get('discussion_message_id') and disc_chat:
        if not await _delete_message(bot, int(disc_chat), event['discussion_message_id'],
                                     "discussion booking reply", event['id']):
            leftovers.append((LEFTOVER_DISCUSSION_REPLY, None))
    return leftovers


async def delete_event_everywhere(context, event):
    """Deletes a cancelled event for good. Eventbrite goes first: if it refuses, nothing else is touched.

    A Telegram message that cannot be deleted does not stop the deletion; it is returned in `leftovers`.
    """
    event_id = event['id']
    reason = await _delete_on_eventbrite(event)
    if reason:
        return DeletionResult(eventbrite_error=reason)

    leftovers = await _delete_public_messages(context.bot, event)

    keep_image = image_path_in_use(event.get('image_path'), event_id)
    try:
        removed = await asyncio.to_thread(delete_event_images, event, keep_image)
        logger.info(f"Deleted {len(removed)} image files of event #{event_id}: {', '.join(removed) or '-'}")
    except Exception as e:
        logger.error(f"Error deleting the images of event #{event_id}: {e}")

    if not delete_event(event_id):
        logger.error(f"Event #{event_id}: the database rows could not be deleted.")
        return DeletionResult(leftovers=leftovers, db_failed=True)
    logger.info(f"Event #{event_id} deleted from the database.")
    return DeletionResult(leftovers=leftovers)
