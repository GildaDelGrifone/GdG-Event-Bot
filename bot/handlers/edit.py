import logging
import os

from telegram import InputMediaPhoto, Update
from telegram.ext import ContextTypes

from core import config
from core.db import get_event, update_event_field
from utils.date_utils import parse_user_date, format_standard_event_date
from utils.image_utils import save_image_locally, delete_local_image, move_image_locally
from utils.templates import format_public_event_message
from bot.common.auth import admin_only, describe_user
from bot.common.messages import is_not_modified_error, truncate_caption, with_html_fallback
from bot.common.parsing import UNLIMITED_SEATS_DISPLAY, extract_event_id_from_reply, parse_seats_input
from bot.common.previews import build_admin_warning_block
from bot.handlers.albums import extract_image_bytes_from_update
from bot.service.posts import update_event_messages

logger = logging.getLogger(__name__)

STATUS_SUFFIXES = {
    'approved': "\n\n✅ APPROVATO",
    'discarded': "\n\n❌ SCARTATO",
    'cancelled': "\n\n⚠️ ANNULLATO",
}

EDIT_COMMAND_FIELDS = {
    "/event_edit_title": "title",
    "/event_edit_date": "date",
    "/event_edit_system": "system",
    "/event_edit_seats": "seats",
    "/event_edit_booked": "booked_seats",
    "/event_edit_host": "host",
    "/event_edit_extra": "extra_info",
    "/event_edit_description": "description",
    "/event_edit_image": "image_path",
    "/event_edit_type": "is_roleplay",
}

ROLEPLAY_TRUE_TOKENS = {"rpg", "gdr", "ruolo", "master", "true", "1", "si", "sì", "yes"}
ROLEPLAY_FALSE_TOKENS = {"boardgame", "gdt", "tavolo", "host", "false", "0", "no", "non rpg", "non gdr"}
CLEAR_EXTRA_TOKENS = {"null", "nessuno", "0", "none", "elimina", "cancella"}


class EditInputError(Exception):
    """Invalid /event_edit_* value; `reply` is shown to the admin."""
    def __init__(self, reply, parse_mode=None):
        super().__init__(reply)
        self.reply = reply
        self.parse_mode = parse_mode


async def _edit_image(update, event_id, current_event, value):
    image_bytes = await extract_image_bytes_from_update(update)
    if not image_bytes:
        raise EditInputError("Devi allegare un'immagine (o un album) a questo comando, oppure rispondere a un'immagine con il comando.")

    old_image_path = current_event.get("image_path")
    new_image_path = save_image_locally(image_bytes, config.DATA_DIR, current_event.get("normalized_date"))
    if not new_image_path:
        raise EditInputError("Errore durante il salvataggio dell'immagine.")

    success = update_event_field(event_id, "image_path", new_image_path)
    if success and old_image_path and old_image_path != new_image_path:
        delete_local_image(old_image_path)
    return success


async def _edit_date(update, event_id, current_event, value):
    parsed = parse_user_date(value)
    if not parsed:
        raise EditInputError(
            "❌ Formato data non valido.\n"
            "Usa il formato DD-MM-YYYY o DD-MM-YYYY HH:MM (es. 05-09-2026 oppure 05-09-2026 21:00) (i / funzionano anche)."
        )
    formatted_date, norm_date = format_standard_event_date(*parsed)
    success = update_event_field(event_id, "date", formatted_date)
    success = update_event_field(event_id, "normalized_date", norm_date) and success

    old_image_path = current_event.get("image_path")
    if success and old_image_path:
        new_img_path = move_image_locally(old_image_path, config.DATA_DIR, norm_date)
        if new_img_path and new_img_path != old_image_path:
            update_event_field(event_id, "image_path", new_img_path)
    return success


async def edit_seats(update, event_id, current_event, value):
    try:
        seats = parse_seats_input(value)
    except ValueError:
        raise EditInputError("Formato non valido. Usa 'X/Y' (es. '2/2'), un numero intero (es. '4'), o 'null'.")

    if seats is None:
        update_event_field(event_id, "max_seats", None)
        update_event_field(event_id, "seats", UNLIMITED_SEATS_DISPLAY)
        return True

    free, total = seats
    if free is None:
        current_booked = current_event.get('booked_seats', 0) or 0
        free = max(0, total - current_booked)
    else:
        update_event_field(event_id, "booked_seats", max(0, total - free))
    update_event_field(event_id, "max_seats", total)
    update_event_field(event_id, "seats", f"{free}/{total}")
    return True


async def _edit_booked_seats(update, event_id, current_event, value):
    try:
        booked = int(value)
    except ValueError:
        raise EditInputError("Il valore per i posti prenotati deve essere un numero intero.")
    success = update_event_field(event_id, "booked_seats", booked)
    max_seats = current_event.get('max_seats')
    if max_seats is not None:
        update_event_field(event_id, "seats", f"{max(0, max_seats - booked)}/{max_seats}")
    return success


async def _edit_extra_info(update, event_id, current_event, value):
    if value.lower() in CLEAR_EXTRA_TOKENS:
        value = ""
    return update_event_field(event_id, "extra_info", value)


async def _edit_roleplay_type(update, event_id, current_event, value):
    clean = value.strip().lower()
    if clean in ROLEPLAY_TRUE_TOKENS:
        new_val = 1
    elif clean in ROLEPLAY_FALSE_TOKENS:
        new_val = 0
    elif clean == "":
        new_val = 0 if current_event.get("is_roleplay") else 1
    else:
        raise EditInputError(
            "❌ Tipo non valido.\n"
            "Usa <code>/event_edit_type rpg</code> (o gdr) per gioco di ruolo (Master),\n"
            "oppure <code>/event_edit_type boardgame</code> (o tavolo) per altri giochi (Host).",
            parse_mode="HTML",
        )
    return update_event_field(event_id, "is_roleplay", new_val)


# Editors take (update, event_id, current_event, value) and return the DB success flag
FIELD_EDITORS = {
    "image_path": _edit_image,
    "date": _edit_date,
    "seats": edit_seats,
    "booked_seats": _edit_booked_seats,
    "extra_info": _edit_extra_info,
    "is_roleplay": _edit_roleplay_type,
}


def _plain_field_editor(field):
    async def edit(update, event_id, current_event, value):
        return update_event_field(event_id, field, value)
    return edit


async def _resolve_edit_target(update, cmd, value):
    """Returns (event_id, target_msg); event_id is None after an explanatory reply has been sent."""
    reply_msg = update.message.reply_to_message

    if cmd == "/event_edit_image" and value.isdigit():
        event_id = int(value)
        target_msg = reply_msg if reply_msg and extract_event_id_from_reply(reply_msg) == event_id else None
        return event_id, target_msg

    if not reply_msg:
        await update.message.reply_text("Rispondi al messaggio dell'evento che vuoi modificare.")
        return None, None

    event_id = extract_event_id_from_reply(reply_msg)
    if not event_id:
        await update.message.reply_text("Impossibile determinare l'ID dell'evento da questo messaggio. Assicurati di rispondere al messaggio con i pulsanti (Publish, Discard, Cancel).")
        return None, None
    return event_id, reply_msg


async def _refresh_admin_message(target_msg, event, image_changed):
    has_photo = bool(getattr(target_msg, "photo", None))
    image_path = event.get('image_path')
    will_have_photo = has_photo or bool(image_changed and image_path and os.path.exists(image_path))
    final_text = format_public_event_message(event)
    warning_block = build_admin_warning_block(
        event, final_text, has_image=will_have_photo, check_date_anomalies=event.get('status') == 'pending'
    )
    new_text = warning_block + final_text + STATUS_SUFFIXES.get(event['status'], "")
    if will_have_photo:
        new_text = truncate_caption(new_text)
    keyboard = target_msg.reply_markup

    try:
        if image_changed and image_path and os.path.exists(image_path):
            if has_photo:
                with open(image_path, 'rb') as f:
                    await with_html_fallback(lambda **kw: target_msg.edit_media(
                        media=InputMediaPhoto(media=f, caption=new_text, **kw), reply_markup=keyboard
                    ))
            else:
                new_msg = None
                with open(image_path, 'rb') as f:
                    new_msg = await with_html_fallback(lambda **kw: target_msg.reply_photo(
                        photo=f, caption=new_text, reply_markup=keyboard, **kw
                    ))
                if new_msg and getattr(new_msg, "message_id", None):
                    update_event_field(event['id'], "admin_message_id", new_msg.message_id)
                try:
                    await target_msg.delete()
                except Exception as del_err:
                    logger.debug(f"Could not delete old admin text message #{getattr(target_msg, 'message_id', None)}: {del_err}")
        elif has_photo:
            await with_html_fallback(lambda **kw: target_msg.edit_caption(caption=new_text, reply_markup=keyboard, **kw))
        else:
            await with_html_fallback(lambda **kw: target_msg.edit_text(text=new_text, reply_markup=keyboard, **kw))
    except Exception as e:
        if not is_not_modified_error(e):
            logger.error(f"Error editing admin message: {e}")


@admin_only()
async def event_edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_parts = (update.message.text or update.message.caption or "").split(maxsplit=1)
    if not text_parts:
        return
    cmd = text_parts[0].lower().split("@")[0]
    value = text_parts[1].strip() if len(text_parts) > 1 else ""

    field = EDIT_COMMAND_FIELDS.get(cmd)
    if not field:
        return

    event_id, target_msg = await _resolve_edit_target(update, cmd, value)
    if not event_id:
        return

    current_event = get_event(event_id)
    if not current_event:
        await update.message.reply_text("Evento non trovato nel database (potrebbe essere stato eliminato o scartato).")
        return

    editor = FIELD_EDITORS.get(field) or _plain_field_editor(field)
    try:
        success = await editor(update, event_id, current_event, value)
    except EditInputError as e:
        await update.message.reply_text(e.reply, parse_mode=e.parse_mode)
        return

    admin_identifier = describe_user(update.effective_user)
    if not success:
        logger.warning(f"{admin_identifier} failed to update field '{field}' to '{value}' for event #{event_id}.")
        await update.message.reply_text("Errore durante l'aggiornamento del database.")
        return

    logger.info(f"{admin_identifier} successfully updated field '{field}' to '{value}' for event #{event_id}.")

    event = get_event(event_id)
    if not event:
        await update.message.reply_text("Evento non trovato nel DB dopo l'aggiornamento.")
        return

    if target_msg:
        await _refresh_admin_message(target_msg, event, image_changed=(field == "image_path"))

    if event['status'] in ['approved', 'cancelled']:
        await update_event_messages(context, event_id, event=event, update_image=(field == "image_path"))

    await update.message.reply_text(f"✅ Campo '{field}' aggiornato con successo!")
