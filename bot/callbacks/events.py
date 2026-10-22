import logging

from core import config
from core.db import (
    delete_event, get_event, update_event_status, update_telegram_message_info,
)
from utils.image_utils import create_story_image, delete_local_image
from utils.templates.approval import (
    APPROVED_SUFFIX, CANCELLED_SUFFIX, DISCARDED_SUFFIX, POPUP_ALREADY_CANCELLED, POPUP_CANCELLATION_ABORTED,
    POPUP_LOADING_LOGO, POPUP_NOTHING_TO_CANCEL_ON_EVENTBRITE, POPUP_REACTIVATED, REACTIVATED_SUFFIX,
    STORY_GENERATED_CAPTION, STORY_GENERATION_ERROR, STORY_GENERATION_PROGRESS, format_approved_without_telegram,
    format_channel_publish_error,
)
from utils.templates.common import POPUP_EVENT_NOT_FOUND
from utils.templates.event import format_public_event_message
from bot.callbacks.notices import send_cancellation_notice, send_reactivation_notice
from bot.common.auth import describe_user
from bot.common.messages import send_image_or_error, truncate_caption, with_html_fallback
from bot.keyboards import (
    get_approved_event_keyboard, get_cancel_confirmation_keyboard, get_cancelled_event_keyboard, get_event_booking_keyboard,
    get_eventbrite_cancel_confirmation_keyboard,
)
from bot.service.eventbrite import (
    cancel_on_eventbrite, cancel_only_on_eventbrite, finish_eventbrite_cancellation, reactivate_on_eventbrite,
    retry_logo_on_eventbrite, start_eventbrite_publish,
)
from bot.service.posts import update_event_messages
from bot.state import runtime_state

logger = logging.getLogger(__name__)

STATUS_SUFFIXES = (APPROVED_SUFFIX, CANCELLED_SUFFIX, REACTIVATED_SUFFIX, DISCARDED_SUFFIX)


def update_status_suffix(msg_text, new_suffix):
    text = msg_text or ""
    for suffix in STATUS_SUFFIXES:
        if text.endswith(suffix):
            text = text[:-len(suffix)]
    return f"{text}{new_suffix}"


async def _mark_admin_card(query, suffix, action, keyboard=None, use_html=False):
    """Swaps the status line on the admin review card (and its buttons, when a keyboard is given)."""
    message = query.message
    new_text = update_status_suffix(message.caption or message.text or "", suffix)
    extra = {"reply_markup": keyboard} if keyboard is not None else {}

    if message.photo:
        new_text = truncate_caption(new_text)
        edit = lambda **kw: query.edit_message_caption(caption=new_text, **extra, **kw)
    else:
        edit = lambda **kw: query.edit_message_text(text=new_text, **extra, **kw)

    try:
        await (with_html_fallback(edit) if use_html else edit())
    except Exception as e:
        logger.error(f"Error updating admin message on {action}: {e}")


async def _publish_to_channel(context, query, event_id, event):
    if not config.PUBLIC_CHANNEL_ID:
        return
    try:
        public_text = format_public_event_message(event)
        keyboard = get_event_booking_keyboard(event_id, event=event, bot_username=getattr(context.bot, "username", None))
        if event.get('image_path'):
            with open(event['image_path'], 'rb') as f:
                pub_msg = await context.bot.send_photo(
                    chat_id=config.PUBLIC_CHANNEL_ID, photo=f, caption=public_text, reply_markup=keyboard, parse_mode="HTML"
                )
        else:
            pub_msg = await context.bot.send_message(
                chat_id=config.PUBLIC_CHANNEL_ID, text=public_text, reply_markup=keyboard, parse_mode="HTML"
            )
        update_telegram_message_info(event_id, pub_msg.message_id, pub_msg.link)
    except Exception as e:
        logger.error(f"Error publishing to public channel: {e}")
        try:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=format_channel_publish_error(event_id, e)
            )
        except Exception:
            pass


async def _send_story_preview(context, chat_id, event):
    # Instagram publishing is disabled for now; admins review the generated story image instead
    await context.bot.send_message(chat_id=chat_id, text=STORY_GENERATION_PROGRESS)
    story_image_path = create_story_image(event, event.get('image_path'), config.DATA_DIR)
    await send_image_or_error(
        context.bot, chat_id, story_image_path,
        caption=STORY_GENERATED_CAPTION,
        error_text=STORY_GENERATION_ERROR,
    )


async def _publish(query, context, event_id, telegram=True):
    """Approves the event; the channel post is skipped for Eventbrite-only publishing (the Solo Eventbrite button)."""
    update_event_status(event_id, "approved")
    event = get_event(event_id)
    await _mark_admin_card(
        query, APPROVED_SUFFIX, "publish", keyboard=get_approved_event_keyboard(event_id, event), use_html=True
    )
    if event:
        if telegram:
            await _publish_to_channel(context, query, event_id, event)
        else:
            logger.info(f"Event #{event_id} approved without a Telegram post.")
            await context.bot.send_message(
                chat_id=query.message.chat_id, reply_to_message_id=query.message.message_id,
                text=format_approved_without_telegram(event_id),
            )
        if not runtime_state.eventbrite_only:  # Eventbrite-only mode: no automatic Instagram story
            await _send_story_preview(context, query.message.chat_id, event)


async def handle_publish_event(query, context, payload):
    await query.answer()
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} approved/published event #{event_id}.")
    await _publish(query, context, event_id)


async def handle_publish_event_with_eventbrite(query, context, payload):
    await query.answer()
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} approved/published event #{event_id} (+ Eventbrite).")
    await _publish(query, context, event_id)
    await start_eventbrite_publish(context, event_id, query.message.chat_id)


async def handle_publish_eventbrite_only(query, context, payload):
    await query.answer()
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} approved event #{event_id} on Eventbrite only.")
    await _publish(query, context, event_id, telegram=False)
    await start_eventbrite_publish(context, event_id, query.message.chat_id)


async def handle_eventbrite_publish(query, context, payload):
    await query.answer()
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} requested Eventbrite publication of event #{event_id}.")
    await start_eventbrite_publish(context, event_id, query.message.chat_id)


async def handle_eventbrite_recreate(query, context, payload):
    await query.answer()
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} requested re-creating event #{event_id} on Eventbrite.")
    try:
        await query.edit_message_reply_markup(reply_markup=None)  # one click only
    except Exception as e:
        logger.debug(f"Could not remove the recreate button: {e}")
    await start_eventbrite_publish(context, event_id, query.message.chat_id, recreate=True)


def _eventbrite_cancellable(event):
    return bool(event and event.get('status') == 'approved' and event.get('eventbrite_event_id')
                and event.get('eventbrite_status') in ('live', 'unpublished'))


async def handle_eventbrite_cancel_ask(query, context, payload):
    """[🚫 Annulla su Eventbrite] only asks for confirmation; the Telegram event is never touched."""
    event_id = int(payload)
    event = get_event(event_id)
    if not _eventbrite_cancellable(event):
        await query.answer(POPUP_NOTHING_TO_CANCEL_ON_EVENTBRITE, show_alert=True)
        return
    logger.info(f"{describe_user(query.from_user)} asked to cancel event #{event_id} on Eventbrite only.")
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=get_eventbrite_cancel_confirmation_keyboard(event_id))
    except Exception as e:
        logger.error(f"Could not show the Eventbrite cancel confirmation for event #{event_id}: {e}")


async def handle_eventbrite_cancel_do(query, context, payload):
    event_id = int(payload)
    event = get_event(event_id)
    if not _eventbrite_cancellable(event):
        await query.answer(POPUP_NOTHING_TO_CANCEL_ON_EVENTBRITE, show_alert=True)
        return
    await query.answer()
    logger.info(f"{describe_user(query.from_user)} cancelled event #{event_id} on Eventbrite only.")
    await cancel_only_on_eventbrite(context, event, query.message.chat_id)


async def handle_eventbrite_logo_retry(query, context, payload):
    await query.answer(POPUP_LOADING_LOGO)
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} retried the Eventbrite logo upload of event #{event_id}.")
    await retry_logo_on_eventbrite(context, event_id, query.message.chat_id)


async def handle_eventbrite_cancel_retry(query, context, payload):
    await query.answer()
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} asked to complete the Eventbrite cancellation of event #{event_id}.")
    event = get_event(event_id)
    if not event:
        await query.answer(POPUP_EVENT_NOT_FOUND, show_alert=True)
        return
    # The order-links message is temporary; the button on the admin card itself must stay
    is_card = query.message.message_id == event.get('admin_message_id')
    await finish_eventbrite_cancellation(
        context, event, query.message.chat_id, temporary_message=None if is_card else query.message
    )


async def handle_discard_event(query, context, payload):
    await query.answer()
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} discarded event #{event_id}.")
    event = get_event(event_id)
    if event and event.get('image_path'):
        delete_local_image(event['image_path'])
    delete_event(event_id)
    await _mark_admin_card(query, DISCARDED_SUFFIX, "discard")


async def _change_published_state(query, context, event_id, status, suffix, keyboard, action, send_notice):
    update_event_status(event_id, status)
    await _mark_admin_card(query, suffix, action, keyboard=keyboard)
    event = get_event(event_id)
    if event:
        await update_event_messages(context, event_id, event=event, current_query=query)
        await send_notice(context, event)


async def handle_cancel_event(query, context, payload):
    """[❌ Annulla Evento] only asks for confirmation; nothing changes until [✅ Conferma …]."""
    event_id = int(payload)
    event = get_event(event_id)
    if not event:
        await query.answer(POPUP_EVENT_NOT_FOUND, show_alert=True)
        return

    logger.info(f"{describe_user(query.from_user)} asked to cancel event #{event_id} (confirmation requested).")
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=get_cancel_confirmation_keyboard(event_id))
    except Exception as e:
        logger.error(f"Could not show the cancel confirmation for event #{event_id}: {e}")


async def handle_cancel_abort(query, context, payload):
    await query.answer(POPUP_CANCELLATION_ABORTED)
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} aborted the cancellation of event #{event_id}.")
    try:
        await query.edit_message_reply_markup(reply_markup=get_approved_event_keyboard(event_id, get_event(event_id)))
    except Exception as e:
        logger.error(f"Could not restore the card buttons of event #{event_id}: {e}")


async def handle_cancel_confirm(query, context, payload):
    event_id = int(payload)
    event = get_event(event_id)
    if not event:
        await query.answer(POPUP_EVENT_NOT_FOUND, show_alert=True)
        return
    if event.get('status') == 'cancelled':
        await query.answer(POPUP_ALREADY_CANCELLED)
        return
    await query.answer()
    logger.info(f"{describe_user(query.from_user)} cancelled event #{event_id}.")
    await _change_published_state(
        query, context, event_id, "cancelled", CANCELLED_SUFFIX, get_cancelled_event_keyboard(event_id), "cancel",
        send_cancellation_notice,
    )
    event = get_event(event_id)
    if event and event.get('eventbrite_event_id'):
        await cancel_on_eventbrite(context, event)


async def handle_reactivate_event(query, context, payload):
    await query.answer(POPUP_REACTIVATED)
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} reactivated event #{event_id}.")
    await _change_published_state(
        query, context, event_id, "approved", APPROVED_SUFFIX, get_approved_event_keyboard(event_id, get_event(event_id)),
        "reactivate", send_reactivation_notice,
    )
    event = get_event(event_id)
    if event and event.get('eventbrite_event_id'):
        await reactivate_on_eventbrite(context, event)
