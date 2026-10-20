import logging

from core import config
from core.db import (
    delete_event, eventbrite_seat_count, get_event, update_event_status, update_telegram_message_info,
)
from utils.image_utils import create_story_image, delete_local_image
from utils.templates import format_public_event_message
from bot.callbacks.notices import send_cancellation_notice, send_reactivation_notice
from bot.common.auth import describe_user
from bot.common.messages import send_image_or_error, truncate_caption, with_html_fallback
from bot.keyboards import (
    get_approved_event_keyboard, get_cancel_confirmation_keyboard, get_cancelled_event_keyboard, get_event_booking_keyboard,
    get_eventbrite_cancel_confirmation_keyboard,
)
from bot.service.eventbrite import (
    cancel_on_eventbrite, cancel_only_on_eventbrite, finish_eventbrite_cancellation, publish_event_to_eventbrite, reactivate_on_eventbrite,
    recreate_on_eventbrite, retry_logo_on_eventbrite,
)
from bot.service.posts import update_event_messages

logger = logging.getLogger(__name__)

APPROVED_SUFFIX = "\n\n✅ APPROVATO"
CANCELLED_SUFFIX = "\n\n⚠️ ANNULLATO"
DISCARDED_SUFFIX = "\n\n❌ SCARTATO"
STATUS_SUFFIXES = (APPROVED_SUFFIX, CANCELLED_SUFFIX, "\n\n✅ RIATTIVATO", DISCARDED_SUFFIX)


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
                text=f"❌ Errore pubblicazione evento #{event_id} sul canale: {e}\nSe la didascalia supera i 1024 caratteri, riduci la descrizione con /event_edit_description e riprova ad approvare."
            )
        except Exception:
            pass


async def _send_story_preview(context, chat_id, event):
    # Instagram publishing is disabled for now; admins review the generated story image instead
    await context.bot.send_message(chat_id=chat_id, text="⏳ Generazione e pubblicazione Storia Instagram in corso...")
    story_image_path = create_story_image(event, event.get('image_path'), config.DATA_DIR)
    await send_image_or_error(
        context.bot, chat_id, story_image_path,
        caption="✅ Immagine Storia generata (Pubblicazione IG disabilitata temporaneamente per test).",
        error_text="❌ Errore durante la generazione dell'immagine della storia.",
    )


async def _publish(query, context, event_id):
    update_event_status(event_id, "approved")
    event = get_event(event_id)
    await _mark_admin_card(
        query, APPROVED_SUFFIX, "publish", keyboard=get_approved_event_keyboard(event_id, event), use_html=True
    )
    if event:
        await _publish_to_channel(context, query, event_id, event)
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
    await publish_event_to_eventbrite(context, event_id, query.message.chat_id)


async def handle_eventbrite_publish(query, context, payload):
    await query.answer()
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} requested Eventbrite publication of event #{event_id}.")
    await publish_event_to_eventbrite(context, event_id, query.message.chat_id)


async def handle_eventbrite_recreate(query, context, payload):
    await query.answer()
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} requested re-creating event #{event_id} on Eventbrite.")
    try:
        await query.edit_message_reply_markup(reply_markup=None)  # one click only
    except Exception as e:
        logger.debug(f"Could not remove the recreate button: {e}")
    await recreate_on_eventbrite(context, event_id, query.message.chat_id)


def _eventbrite_cancellable(event):
    return bool(event and event.get('status') == 'approved' and event.get('eventbrite_event_id')
                and event.get('eventbrite_status') in ('live', 'unpublished'))


async def handle_eventbrite_cancel_ask(query, context, payload):
    """[🚫 Annulla su Eventbrite] only asks for confirmation; the Telegram event is never touched."""
    event_id = int(payload)
    event = get_event(event_id)
    if not _eventbrite_cancellable(event):
        await query.answer("Niente da annullare su Eventbrite per questo evento.", show_alert=True)
        return
    eb_seats = eventbrite_seat_count(event_id)
    warning = "Annullare l'evento solo su Eventbrite? Su Telegram resta attivo e il gruppo non viene avvisato."
    if eb_seats:
        warning += f" {eb_seats} posti Eventbrite: riceverai i link per annullare ogni ordine."
    logger.info(f"{describe_user(query.from_user)} asked to cancel event #{event_id} on Eventbrite only.")
    await query.answer(warning, show_alert=True)
    try:
        await query.edit_message_reply_markup(reply_markup=get_eventbrite_cancel_confirmation_keyboard(event_id))
    except Exception as e:
        logger.error(f"Could not show the Eventbrite cancel confirmation for event #{event_id}: {e}")


async def handle_eventbrite_cancel_do(query, context, payload):
    event_id = int(payload)
    event = get_event(event_id)
    if not _eventbrite_cancellable(event):
        await query.answer("Niente da annullare su Eventbrite per questo evento.", show_alert=True)
        return
    await query.answer()
    logger.info(f"{describe_user(query.from_user)} cancelled event #{event_id} on Eventbrite only.")
    await cancel_only_on_eventbrite(context, event, query.message.chat_id)


async def handle_eventbrite_logo_retry(query, context, payload):
    await query.answer("Carico il logo…")
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} retried the Eventbrite logo upload of event #{event_id}.")
    await retry_logo_on_eventbrite(context, event_id, query.message.chat_id)


async def handle_eventbrite_cancel_retry(query, context, payload):
    await query.answer()
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} asked to complete the Eventbrite cancellation of event #{event_id}.")
    event = get_event(event_id)
    if not event:
        await query.answer("Evento non trovato.", show_alert=True)
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
        await query.answer("Evento non trovato.", show_alert=True)
        return

    eb_seats = eventbrite_seat_count(event_id)
    telegram_seats = max(0, int(event.get('booked_seats') or 0) - eb_seats)
    warning = f"Annullare l'evento? Gli iscritti verranno avvisati ({telegram_seats} posti su Telegram)."
    if eb_seats:
        warning += f" {eb_seats} posti Eventbrite: dopo la conferma riceverai i link per annullare ogni ordine."
    logger.info(f"{describe_user(query.from_user)} asked to cancel event #{event_id} (confirmation requested).")
    await query.answer(warning, show_alert=True)
    try:
        await query.edit_message_reply_markup(reply_markup=get_cancel_confirmation_keyboard(event_id))
    except Exception as e:
        logger.error(f"Could not show the cancel confirmation for event #{event_id}: {e}")


async def handle_cancel_abort(query, context, payload):
    await query.answer("Annullamento interrotto.")
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
        await query.answer("Evento non trovato.", show_alert=True)
        return
    if event.get('status') == 'cancelled':
        await query.answer("Evento già annullato.")
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
    await query.answer("Evento riattivato!")
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} reactivated event #{event_id}.")
    await _change_published_state(
        query, context, event_id, "approved", APPROVED_SUFFIX, get_approved_event_keyboard(event_id, get_event(event_id)),
        "reactivate", send_reactivation_notice,
    )
    event = get_event(event_id)
    if event and event.get('eventbrite_event_id'):
        await reactivate_on_eventbrite(context, event)
