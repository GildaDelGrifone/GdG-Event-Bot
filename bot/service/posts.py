import asyncio
import logging
import os

from telegram import InputMediaPhoto
from telegram.error import RetryAfter

from core import config
from core.db import get_event, update_discussion_message_info
from utils.templates import format_public_event_message
from bot.common.messages import is_not_modified_error
from bot.keyboards import get_event_booking_keyboard

logger = logging.getLogger(__name__)


async def _execute_with_retry(coro_fn, max_retries=2):
    """Runs coro_fn(), retrying when Telegram rate-limits us (RetryAfter)."""
    for attempt in range(max_retries + 1):
        try:
            return await coro_fn()
        except RetryAfter as e:
            if attempt >= max_retries:
                raise
            wait_sec = getattr(e, 'retry_after', 1) or 1
            logger.warning(f"Flood control exceeded. Waiting {wait_sec}s before retry (attempt {attempt + 1}/{max_retries})...")
            await asyncio.sleep(wait_sec)


async def _edit_post_body(bot, message_id, text, keyboard, caption_first):
    """Edits the caption (or text) of a channel post, switching kind only when Telegram says the post has none."""
    def edit_caption():
        return bot.edit_message_caption(
            chat_id=config.PUBLIC_CHANNEL_ID, message_id=message_id, caption=text, reply_markup=keyboard, parse_mode="HTML"
        )

    def edit_text():
        return bot.edit_message_text(
            chat_id=config.PUBLIC_CHANNEL_ID, message_id=message_id, text=text, reply_markup=keyboard, parse_mode="HTML"
        )

    if caption_first:
        first, second, wrong_kind = edit_caption, edit_text, "no caption in the message to edit"
    else:
        first, second, wrong_kind = edit_text, edit_caption, "no text in the message to edit"

    try:
        await _execute_with_retry(first)
    except Exception as e:
        if is_not_modified_error(e):
            return
        if wrong_kind not in str(e).lower():
            raise
        try:
            await _execute_with_retry(second)
        except Exception as e_second:
            if not is_not_modified_error(e_second):
                raise


async def _sync_public_post(bot, event_id, event, public_text, keyboard, update_image):
    if not (config.PUBLIC_CHANNEL_ID and event.get('telegram_message_id') and event.get('status') in ('approved', 'cancelled')):
        return

    message_id = event['telegram_message_id']
    image_path = event.get('image_path')

    if update_image and image_path and os.path.exists(image_path):
        try:
            with open(image_path, 'rb') as f:
                img_bytes = f.read()
            await _execute_with_retry(lambda: bot.edit_message_media(
                chat_id=config.PUBLIC_CHANNEL_ID,
                message_id=message_id,
                media=InputMediaPhoto(media=img_bytes, caption=public_text, parse_mode="HTML"),
                reply_markup=keyboard,
            ))
        except Exception as e:
            if not is_not_modified_error(e):
                logger.error(f"Error editing message media in public channel for event {event_id}: {e}")
        return

    try:
        await _edit_post_body(bot, message_id, public_text, keyboard, caption_first=bool(image_path))
    except Exception as e:
        if not is_not_modified_error(e):
            logger.error(f"Error updating public channel message for event {event_id}: {e}")


async def _sync_discussion_reply(bot, event_id, event, keyboard, current_query):
    disc_msg_id = event.get('discussion_message_id')
    disc_chat_id = event.get('discussion_chat_id') or config.DISCUSSION_GROUP_ID

    # A click inside the discussion group tells us (and lets us store) where the booking reply lives.
    # We explicitly ignore clicks from the admin chat and public channel so we don't accidentally
    # overwrite the discussion ID and strip the admin card's buttons.
    if current_query and current_query.message:
        chat_id_str = str(current_query.message.chat_id)
        admin_chat = str(config.ADMIN_CHAT_ID) if config.ADMIN_CHAT_ID is not None else None
        public_chat = str(config.PUBLIC_CHANNEL_ID) if config.PUBLIC_CHANNEL_ID is not None else None
        if chat_id_str not in (public_chat, admin_chat):
            disc_msg_id = current_query.message.message_id
            disc_chat_id = current_query.message.chat_id
            update_discussion_message_info(event_id, disc_msg_id, disc_chat_id)
            try:
                await _execute_with_retry(lambda: current_query.edit_message_reply_markup(reply_markup=keyboard))
                return
            except Exception as e:
                if not is_not_modified_error(e):
                    logger.debug(f"Could not edit reply markup on current query message: {e}")

    if not (disc_msg_id and disc_chat_id):
        return
    try:
        await _execute_with_retry(lambda: bot.edit_message_reply_markup(
            chat_id=int(disc_chat_id), message_id=int(disc_msg_id), reply_markup=keyboard
        ))
    except Exception as e:
        if not is_not_modified_error(e):
            logger.error(f"Error updating discussion reply markup for event {event_id}: {e}")


async def update_event_messages(context, event_id, event=None, current_query=None, update_image=False):
    """Re-renders an event's public channel post and its discussion-group booking reply."""
    if event is None:
        event = get_event(event_id)
    if not event:
        return

    public_text = format_public_event_message(event)
    keyboard = None
    if event.get('status') == 'approved':
        bot_username = getattr(getattr(context, 'bot', None), "username", None)
        keyboard = get_event_booking_keyboard(event_id, event=event, bot_username=bot_username)

    await _sync_public_post(context.bot, event_id, event, public_text, keyboard, update_image)
    await _sync_discussion_reply(context.bot, event_id, event, keyboard, current_query)
