import logging

from core import config
from core.db import update_event_status, delete_event, get_event, update_telegram_message_info
from utils.image_utils import create_story_image, delete_local_image
from utils.templates import format_public_event_message
from bot.callbacks.notices import send_cancellation_notice, send_reactivation_notice
from bot.common.auth import describe_user
from bot.common.messages import send_image_or_error, truncate_caption, with_html_fallback
from bot.keyboards import get_event_booking_keyboard, get_approved_event_keyboard, get_cancelled_event_keyboard
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


async def handle_publish_event(query, context, payload):
    await query.answer()
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} approved/published event #{event_id}.")
    update_event_status(event_id, "approved")
    await _mark_admin_card(query, APPROVED_SUFFIX, "publish", keyboard=get_approved_event_keyboard(event_id), use_html=True)

    event = get_event(event_id)
    if event:
        await _publish_to_channel(context, query, event_id, event)
        await _send_story_preview(context, query.message.chat_id, event)


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
    await query.answer()
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} cancelled event #{event_id}.")
    await _change_published_state(
        query, context, event_id, "cancelled", CANCELLED_SUFFIX, get_cancelled_event_keyboard(event_id), "cancel",
        send_cancellation_notice,
    )


async def handle_reactivate_event(query, context, payload):
    await query.answer("Evento riattivato!")
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} reactivated event #{event_id}.")
    await _change_published_state(
        query, context, event_id, "approved", APPROVED_SUFFIX, get_approved_event_keyboard(event_id), "reactivate",
        send_reactivation_notice,
    )
