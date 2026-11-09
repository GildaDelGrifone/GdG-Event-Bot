"""Announces the people the waitlist moved into a freed seat (core.db.promote_waitlist does the booking)."""
import logging

from telegram.error import TelegramError

from core import config
from utils.templates.booking import format_waitlist_promoted_dm, format_waitlist_promoted_notice
from utils.templates.common import format_event_title_link
from bot.common.messages import send_with_reply_fallback
from bot.service.mentions import format_subscriber_tag

logger = logging.getLogger(__name__)


async def announce_promotions(bot, event, promoted):
    """Tags each promoted user in the discussion group (reply to the booking message) and tries a DM.

    The DM only reaches users who have opened a private chat with the bot; anything else is ignored.
    """
    event_link = format_event_title_link(event)
    for entry in promoted:
        logger.info(f"Waitlist: user {entry['user_id']} got a seat for event #{event['id']}.")
        tag = format_subscriber_tag(entry.get('username'), entry.get('full_name'), entry.get('user_id')) or "Utente"
        if config.DISCUSSION_GROUP_ID and event.get('telegram_message_id'):
            reply_id = event.get('discussion_message_id')
            await send_with_reply_fallback(
                bot, int(config.DISCUSSION_GROUP_ID), format_waitlist_promoted_notice(tag, event_link),
                int(reply_id) if reply_id else None, log=logger, label="waitlist promotion notice",
            )
        try:
            await bot.send_message(chat_id=entry['user_id'], text=format_waitlist_promoted_dm(event_link),
                                   parse_mode="HTML", disable_web_page_preview=True)
        except TelegramError as e:
            logger.debug(f"Waitlist: no DM to user {entry['user_id']}: {e}")
