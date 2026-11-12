import asyncio
import logging

from telegram import InlineKeyboardMarkup
from telegram.error import TelegramError

from core import config
from core.db import (
    discard_event, get_event, restore_discarded_event, update_event_status, update_telegram_message_info,
)
from utils.image_utils import create_story_image
from utils.night_images import restore_image_file
from utils.templates.approval import (
    APPROVED_SUFFIX, CANCELLED_SUFFIX, DELETED_SUFFIX, DISCARDED_SUFFIX, POPUP_ALREADY_CANCELLED, POPUP_ALREADY_DELETED,
    POPUP_CANCELLATION_ABORTED, POPUP_DELETE_EB_BUSY, POPUP_DELETE_EB_ORDERS_OPEN, POPUP_DELETE_ONLY_CANCELLED,
    POPUP_DELETION_ABORTED, format_cancel_done, format_delete_db_failed, format_delete_done, format_eb_cancel_done,
    format_delete_eventbrite_failed, format_event_deleted_report,
    POPUP_LOADING_LOGO, POPUP_NOTHING_TO_CANCEL_ON_EVENTBRITE, POPUP_REACTIVATED, POPUP_RESTORE_GONE, POPUP_RESTORED,
    POPUP_RESTORED_WITHOUT_IMAGE, REACTIVATED_SUFFIX,
    STORY_GENERATED_CAPTION, STORY_GENERATION_ERROR, STORY_GENERATION_PROGRESS, format_approved_without_telegram,
    format_channel_publish_error, format_stale_card_popup,
)
from utils.templates.common import POPUP_EVENT_NOT_FOUND
from utils.templates.event import format_public_event_message
from bot.callbacks.notices import send_cancellation_notice, send_reactivation_notice
from bot.common.auth import describe_user
from bot.common.media import send_photo_resilient
from bot.common.messages import edit_card, send_image_or_error, with_html_fallback
from bot.keyboards import (
    COMMAND_MARKER, get_approval_keyboard, get_approved_event_keyboard, get_cancel_confirmation_keyboard, get_discarded_event_keyboard, get_cancelled_event_keyboard, get_event_booking_keyboard,
    get_delete_confirmation_keyboard, get_eventbrite_cancel_confirmation_keyboard,
)
from bot.service.deletion import delete_event_everywhere
from bot.service.edits import redraw_stored_admin_card
from bot.service.eventbrite import (
    cancel_on_eventbrite, cancel_only_on_eventbrite, eventbrite_cancellable, finish_eventbrite_cancellation,
    reactivate_on_eventbrite,
    retry_logo_on_eventbrite, start_eventbrite_publish,
)
from bot.service.posts import update_event_messages
from bot.state import runtime_state

logger = logging.getLogger(__name__)

STATUS_SUFFIXES = (APPROVED_SUFFIX, CANCELLED_SUFFIX, REACTIVATED_SUFFIX, DISCARDED_SUFFIX, DELETED_SUFFIX)


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

    edit = lambda **kw: edit_card(query, new_text, **extra, **kw)

    try:
        await (with_html_fallback(edit) if use_html else edit())
    except Exception as e:
        logger.error(f"Error updating admin message on {action}: {e}")


def _parse_payload(payload):
    """(event_id, from_command): confirmation prompts sent by a command carry COMMAND_MARKER after the id."""
    from_command = payload.endswith(COMMAND_MARKER)
    return int(payload[:-len(COMMAND_MARKER)] if from_command else payload), from_command


async def _set_card(query, context, from_command, event, suffix, action, keyboard):
    """Status line and buttons of the admin card: the clicked card, or the stored one after a command prompt."""
    if from_command:
        await redraw_stored_admin_card(context.bot, event, suffix, keyboard)
    else:
        await _mark_admin_card(query, suffix, action, keyboard=keyboard)


async def _close_prompt(query, text):
    """Replaces a command's confirmation prompt with the outcome, without buttons."""
    try:
        await edit_card(query, text)
    except Exception as e:
        logger.debug(f"Could not close the confirmation prompt: {e}")


async def _publish_to_channel(context, query, event_id, event):
    if not config.PUBLIC_CHANNEL_ID:
        return
    try:
        public_text = format_public_event_message(event)
        keyboard = get_event_booking_keyboard(event_id, event=event, bot_username=getattr(context.bot, "username", None))
        if event.get('image_path'):
            pub_msg = await send_photo_resilient(lambda photo, **kw: context.bot.send_photo(
                chat_id=config.PUBLIC_CHANNEL_ID, photo=photo, caption=public_text, reply_markup=keyboard,
                parse_mode="HTML", **kw
            ), event['image_path'], html=False)
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
        except TelegramError as e:
            logger.debug(f"Could not report channel publish error to admin chat: {e}")


async def _send_story_preview(context, chat_id, event):
    # Instagram publishing is disabled for now; admins review the generated story image instead
    try:
        await context.bot.send_message(chat_id=chat_id, text=STORY_GENERATION_PROGRESS)
    except Exception as e:
        logger.warning(f"Failed to send story generation progress message: {e}")
    story_image_path = await asyncio.to_thread(create_story_image, event, event.get('image_path'), config.DATA_DIR)
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


async def _refuse_stale_card(query, event_id):
    """True (after a popup and a card refresh) when the event is no longer pending.

    A timed-out upload can deliver a second approval card; its Publish / Discard buttons must not act
    on an event that was already published or cancelled through the other card.
    """
    event = get_event(event_id)
    if not event or event.get('status') == 'pending':
        return False
    logger.info(f"{describe_user(query.from_user)} pressed a stale approval button on event #{event_id} "
                f"(status {event['status']}); ignored.")
    await query.answer(format_stale_card_popup(event['status']), show_alert=True)
    await _show_real_state(query, event)
    return True


async def _show_real_state(query, event):
    """Puts the status line and buttons that match the event's current status on the clicked card."""
    event_id, status = event['id'], event.get('status')
    if status == 'cancelled':
        await _mark_admin_card(query, CANCELLED_SUFFIX, "stale card", keyboard=get_cancelled_event_keyboard(event_id))
    elif status == 'discarded':
        await _mark_admin_card(query, DISCARDED_SUFFIX, "stale card", keyboard=get_discarded_event_keyboard(event_id))
    elif status == 'pending':
        await _mark_admin_card(query, "", "stale card", keyboard=get_approval_keyboard(event_id))
    else:
        await _mark_admin_card(query, APPROVED_SUFFIX, "stale card",
                               keyboard=get_approved_event_keyboard(event_id, event), use_html=True)


async def handle_publish_event(query, context, payload):
    event_id = int(payload)
    if await _refuse_stale_card(query, event_id):
        return
    await query.answer()
    logger.info(f"{describe_user(query.from_user)} approved/published event #{event_id}.")
    await _publish(query, context, event_id)


async def handle_publish_event_with_eventbrite(query, context, payload):
    event_id = int(payload)
    if await _refuse_stale_card(query, event_id):
        return
    await query.answer()
    logger.info(f"{describe_user(query.from_user)} approved/published event #{event_id} (+ Eventbrite).")
    await _publish(query, context, event_id)
    await start_eventbrite_publish(context, event_id, query.message.chat_id)


async def handle_publish_eventbrite_only(query, context, payload):
    event_id = int(payload)
    if await _refuse_stale_card(query, event_id):
        return
    await query.answer()
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


async def handle_eventbrite_cancel_ask(query, context, payload):
    """[🚫 Annulla su Eventbrite] only asks for confirmation; the Telegram event is never touched."""
    event_id = int(payload)
    event = get_event(event_id)
    if not eventbrite_cancellable(event):
        await query.answer(POPUP_NOTHING_TO_CANCEL_ON_EVENTBRITE, show_alert=True)
        return
    logger.info(f"{describe_user(query.from_user)} asked to cancel event #{event_id} on Eventbrite only.")
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=get_eventbrite_cancel_confirmation_keyboard(event_id))
    except Exception as e:
        logger.error(f"Could not show the Eventbrite cancel confirmation for event #{event_id}: {e}")


async def handle_eventbrite_cancel_do(query, context, payload):
    event_id, from_command = _parse_payload(payload)
    event = get_event(event_id)
    if not eventbrite_cancellable(event):
        await query.answer(POPUP_NOTHING_TO_CANCEL_ON_EVENTBRITE, show_alert=True)
        if from_command:
            await _close_prompt(query, POPUP_NOTHING_TO_CANCEL_ON_EVENTBRITE)
        return
    await query.answer()
    logger.info(f"{describe_user(query.from_user)} cancelled event #{event_id} on Eventbrite only.")
    if from_command:  # the card is refreshed by cancel_only_on_eventbrite through admin_message_id
        await _close_prompt(query, format_eb_cancel_done(event_id))
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
    event_id = int(payload)
    if await _refuse_stale_card(query, event_id):
        return
    await query.answer()
    logger.info(f"{describe_user(query.from_user)} discarded event #{event_id} "
                f"(kept {config.DISCARDED_RETENTION_DAYS} days, restorable).")
    discard_event(event_id)
    await _mark_admin_card(query, DISCARDED_SUFFIX, "discard", keyboard=get_discarded_event_keyboard(event_id))


async def handle_restore_event(query, context, payload):
    """`[↩️ Ripristina]` on a discarded card: the event goes back to pending with the approval buttons."""
    event_id = int(payload)
    event = get_event(event_id)
    if not event:
        await query.answer(POPUP_RESTORE_GONE, show_alert=True)
        await _mark_admin_card(query, DISCARDED_SUFFIX, "restore", keyboard=InlineKeyboardMarkup([]))
        return
    if not restore_discarded_event(event_id):
        await query.answer(format_stale_card_popup(event['status']), show_alert=True)
        await _show_real_state(query, event)
        return
    logger.info(f"{describe_user(query.from_user)} restored discarded event #{event_id}.")
    image_ok = not event.get('image_path') or restore_image_file(event['image_path'])
    await query.answer(POPUP_RESTORED if image_ok else POPUP_RESTORED_WITHOUT_IMAGE, show_alert=not image_ok)
    await _mark_admin_card(query, "", "restore", keyboard=get_approval_keyboard(event_id))


async def _change_published_state(query, context, event_id, status, suffix, keyboard, action, send_notice,
                                  from_command=False):
    update_event_status(event_id, status)
    event = get_event(event_id)
    await _set_card(query, context, from_command, event or {'id': event_id}, suffix, action, keyboard)
    if event:
        # A command prompt is not the discussion reply, so it must not be passed on as the message to edit
        await update_event_messages(context, event_id, event=event, current_query=None if from_command else query)
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
    event_id, from_command = _parse_payload(payload)
    logger.info(f"{describe_user(query.from_user)} aborted the cancellation of event #{event_id}.")
    if from_command:  # the card was never touched
        await _close_prompt(query, POPUP_CANCELLATION_ABORTED)
        return
    try:
        await query.edit_message_reply_markup(reply_markup=get_approved_event_keyboard(event_id, get_event(event_id)))
    except Exception as e:
        logger.error(f"Could not restore the card buttons of event #{event_id}: {e}")


async def handle_cancel_confirm(query, context, payload):
    event_id, from_command = _parse_payload(payload)
    event = get_event(event_id)
    if not event or event.get('status') == 'cancelled':
        if not event:
            await query.answer(POPUP_EVENT_NOT_FOUND, show_alert=True)
        else:
            await query.answer(POPUP_ALREADY_CANCELLED)
        if from_command:
            await _close_prompt(query, POPUP_ALREADY_CANCELLED if event else POPUP_EVENT_NOT_FOUND)
        return
    await query.answer()
    logger.info(f"{describe_user(query.from_user)} cancelled event #{event_id}.")
    if from_command:
        await _close_prompt(query, format_cancel_done(event_id))
    await _change_published_state(
        query, context, event_id, "cancelled", CANCELLED_SUFFIX, get_cancelled_event_keyboard(event_id), "cancel",
        send_cancellation_notice, from_command=from_command,
    )
    event = get_event(event_id)
    if event and event.get('eventbrite_event_id'):
        await cancel_on_eventbrite(context, event)


async def handle_reactivate_event(query, context, payload):
    event_id = int(payload)
    if not get_event(event_id):  # deleted for good through another card
        await query.answer(POPUP_EVENT_NOT_FOUND, show_alert=True)
        return
    await query.answer(POPUP_REACTIVATED)
    logger.info(f"{describe_user(query.from_user)} reactivated event #{event_id}.")
    await _change_published_state(
        query, context, event_id, "approved", APPROVED_SUFFIX, get_approved_event_keyboard(event_id, get_event(event_id)),
        "reactivate", send_reactivation_notice,
    )
    event = get_event(event_id)
    if event and event.get('eventbrite_event_id'):
        await reactivate_on_eventbrite(context, event)


async def _refuse_delete(query, event, from_command=False):
    """True (after a popup) when the event cannot be deleted: already gone, or not cancelled."""
    if event and event.get('status') == 'cancelled':
        return False
    popup = POPUP_DELETE_ONLY_CANCELLED if event else POPUP_ALREADY_DELETED
    await query.answer(popup, show_alert=True)
    if from_command:
        await _close_prompt(query, popup)
    elif not event:
        await _mark_admin_card(query, DELETED_SUFFIX, "delete", keyboard=InlineKeyboardMarkup([]))
    else:
        await _show_real_state(query, event)
    return True


async def _restore_cancelled_buttons(query, event_id):
    try:
        await query.edit_message_reply_markup(reply_markup=get_cancelled_event_keyboard(event_id))
    except Exception as e:
        logger.error(f"Could not restore the cancelled-card buttons of event #{event_id}: {e}")


async def _reply_to_card(context, query, text):
    try:
        await context.bot.send_message(
            chat_id=query.message.chat_id, reply_to_message_id=query.message.message_id, text=text,
            disable_web_page_preview=True,
        )
    except TelegramError as e:
        logger.error(f"Could not reply to the admin card: {e}")


async def handle_delete_event(query, context, payload):
    """[🗑️ Elimina evento] on a cancelled card only asks for confirmation: the deletion cannot be undone."""
    event_id = int(payload)
    if await _refuse_delete(query, get_event(event_id)):
        return
    logger.info(f"{describe_user(query.from_user)} asked to delete event #{event_id} (confirmation requested).")
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=get_delete_confirmation_keyboard(event_id))
    except Exception as e:
        logger.error(f"Could not show the delete confirmation for event #{event_id}: {e}")


async def handle_delete_abort(query, context, payload):
    event_id, from_command = _parse_payload(payload)
    if await _refuse_delete(query, get_event(event_id), from_command):
        return
    await query.answer(POPUP_DELETION_ABORTED)
    logger.info(f"{describe_user(query.from_user)} aborted the deletion of event #{event_id}.")
    if from_command:  # the card was never touched
        await _close_prompt(query, POPUP_DELETION_ABORTED)
    else:
        await _restore_cancelled_buttons(query, event_id)


async def handle_delete_confirm(query, context, payload):
    """Deletes a cancelled event everywhere except the admin chat (see bot.service.deletion)."""
    event_id, from_command = _parse_payload(payload)
    event = get_event(event_id)
    if await _refuse_delete(query, event, from_command):
        return
    if event_id in runtime_state.eventbrite_publishing:
        await query.answer(POPUP_DELETE_EB_BUSY, show_alert=True)
        return
    if event.get('eventbrite_event_id') and event.get('eventbrite_status') == 'closed':
        await query.answer(POPUP_DELETE_EB_ORDERS_OPEN, show_alert=True)
        if from_command:
            await _close_prompt(query, POPUP_DELETE_EB_ORDERS_OPEN)
        else:
            await _restore_cancelled_buttons(query, event_id)
        return
    await query.answer()
    logger.info(f"{describe_user(query.from_user)} confirmed the permanent deletion of event #{event_id}.")
    try:  # one click only: a second confirm while Eventbrite answers must not start another deletion
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as e:
        logger.debug(f"Could not remove the delete confirmation buttons: {e}")

    result = await delete_event_everywhere(context, event)
    failure = (format_delete_eventbrite_failed(event_id, result.eventbrite_error) if result.eventbrite_error
               else format_delete_db_failed(event_id) if result.db_failed else None)
    if failure:
        if from_command:  # the card still shows the cancelled buttons: only the prompt changes
            await _close_prompt(query, failure)
        else:
            await _reply_to_card(context, query, failure)
            await _restore_cancelled_buttons(query, event_id)
        return
    await _set_card(query, context, from_command, event, DELETED_SUFFIX, "delete", InlineKeyboardMarkup([]))
    if from_command:
        await _close_prompt(query, format_delete_done(event_id))
    if result.leftovers:
        await _reply_to_card(context, query, format_event_deleted_report(event_id, result.leftovers))
