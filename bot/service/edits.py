"""Event field edits shared by /event_edit_* (bot.handlers.edit) and the ✏️ Modifica menu (bot.callbacks.edit_menu)."""
import logging
import os

from telegram import InputMediaPhoto

from core import config
from core.db import eventbrite_seat_count, get_event, update_event_field
from utils.date_utils import parse_user_date, format_standard_event_date
from utils.image_utils import move_image_locally
from utils.templates.approval import APPROVED_SUFFIX, CANCELLED_SUFFIX, DISCARDED_SUFFIX
from utils.templates.edit import (
    EDIT_BOOKED_INVALID, EDIT_DATE_INVALID, EDIT_DB_ERROR, EDIT_EVENT_MISSING_AFTER_UPDATE,
    EDIT_EVENT_NOT_FOUND, EDIT_EXTRA_ADD_USAGE, EDIT_SEATS_INVALID, EDIT_TYPE_INVALID,
    format_caption_overflow_warning, format_edit_done, format_edit_eventbrite_seats_blocked,
)
from utils.templates.event import format_public_event_message
from bot.common.auth import describe_user
from bot.common.media import send_photo_resilient
from bot.common.messages import CAPTION_LIMIT, is_not_modified_error, truncate_caption, with_html_fallback
from bot.common.parsing import UNLIMITED_SEATS_DISPLAY, parse_seats_input
from bot.common.previews import build_admin_warning_block
from bot.service.posts import update_event_messages

logger = logging.getLogger(__name__)

STATUS_SUFFIXES = {
    'approved': APPROVED_SUFFIX,
    'discarded': DISCARDED_SUFFIX,
    'cancelled': CANCELLED_SUFFIX,
}

EDIT_COMMAND_FIELDS = {
    "/event_edit_title": "title",
    "/event_edit_date": "date",
    "/event_edit_system": "system",
    "/event_edit_seats": "seats",
    "/event_edit_booked": "booked_seats",
    "/event_edit_host": "host",
    "/event_edit_extra": "extra_info",
    "/event_edit_extra_add": "extra_info",
    "/event_edit_description": "description",
    "/event_edit_image": "image_path",
    "/event_edit_type": "is_roleplay",
}

# Fields shown on the Eventbrite listing: editing one of them re-pushes the event page
EVENTBRITE_CONTENT_FIELDS = frozenset({"title", "date", "system", "host", "extra_info", "description", "is_roleplay", "seats"})

ROLEPLAY_TRUE_TOKENS = {"rpg", "gdr", "ruolo", "master", "true", "1", "si", "sì", "yes"}
ROLEPLAY_FALSE_TOKENS = {"boardgame", "gdt", "tavolo", "host", "false", "0", "no", "non rpg", "non gdr"}
CLEAR_EXTRA_TOKENS = {"null", "nessuno", "0", "none", "elimina", "cancella"}


class EditInputError(Exception):
    """Invalid /event_edit_* value; `reply` is shown to the admin."""
    def __init__(self, reply, parse_mode=None):
        super().__init__(reply)
        self.reply = reply
        self.parse_mode = parse_mode


def _ensure_booked_not_below_eventbrite(event_id, new_booked):
    eb_seats = eventbrite_seat_count(event_id)
    if new_booked < eb_seats:
        raise EditInputError(format_edit_eventbrite_seats_blocked(eb_seats))


async def _edit_date(update, event_id, current_event, value):
    parsed = parse_user_date(value)
    if not parsed:
        raise EditInputError(EDIT_DATE_INVALID)
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
        raise EditInputError(EDIT_SEATS_INVALID)

    if seats is None:
        update_event_field(event_id, "max_seats", None)
        update_event_field(event_id, "seats", UNLIMITED_SEATS_DISPLAY)
        return True

    free, total = seats
    if free is None:
        current_booked = current_event.get('booked_seats', 0) or 0
        free = max(0, total - current_booked)
    else:
        _ensure_booked_not_below_eventbrite(event_id, max(0, total - free))
        update_event_field(event_id, "booked_seats", max(0, total - free))
    update_event_field(event_id, "max_seats", total)
    update_event_field(event_id, "seats", f"{free}/{total}")
    return True


async def _edit_booked_seats(update, event_id, current_event, value):
    try:
        booked = int(value)
    except ValueError:
        raise EditInputError(EDIT_BOOKED_INVALID)
    _ensure_booked_not_below_eventbrite(event_id, booked)
    success = update_event_field(event_id, "booked_seats", booked)
    max_seats = current_event.get('max_seats')
    if max_seats is not None:
        update_event_field(event_id, "seats", f"{max(0, max_seats - booked)}/{max_seats}")
    return success


async def _edit_extra_info(update, event_id, current_event, value):
    if value.lower() in CLEAR_EXTRA_TOKENS:
        value = ""
    return update_event_field(event_id, "extra_info", value)


async def _edit_extra_info_add(update, event_id, current_event, value):
    if not value:
        raise EditInputError(EDIT_EXTRA_ADD_USAGE, parse_mode="HTML")

    current_extra = (current_event.get("extra_info") or "").strip()
    if current_extra:
        new_extra = f"{current_extra}\n{value}"
    else:
        new_extra = value

    temp_event = dict(current_event)
    temp_event["extra_info"] = new_extra
    final_text = format_public_event_message(temp_event)

    if len(final_text) > CAPTION_LIMIT and update is not None:
        warning_msg = format_caption_overflow_warning(len(final_text), CAPTION_LIMIT)
        await with_html_fallback(lambda **kw: update.message.reply_text(warning_msg, **kw))

    return update_event_field(event_id, "extra_info", new_extra)


async def _edit_roleplay_type(update, event_id, current_event, value):
    clean = value.strip().lower()
    if clean in ROLEPLAY_TRUE_TOKENS:
        new_val = 1
    elif clean in ROLEPLAY_FALSE_TOKENS:
        new_val = 0
    elif clean == "":
        new_val = 0 if current_event.get("is_roleplay") else 1
    else:
        raise EditInputError(EDIT_TYPE_INVALID, parse_mode="HTML")
    return update_event_field(event_id, "is_roleplay", new_val)


# Editors take (update, event_id, current_event, value) and return the DB success flag. `update` is the admin's
# message (None for a button press); the image editor needs an album download, so it lives in bot.handlers.edit.
FIELD_EDITORS = {
    "/event_edit_extra_add": _edit_extra_info_add,
    "extra_info_add": _edit_extra_info_add,
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


async def refresh_admin_message(target_msg, event, image_changed, keyboard=None):
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
    keyboard = keyboard if keyboard is not None else target_msg.reply_markup

    try:
        if image_changed and image_path and os.path.exists(image_path):
            if has_photo:
                await send_photo_resilient(lambda photo, parse_mode=None, **kw: target_msg.edit_media(
                    media=InputMediaPhoto(media=photo, caption=new_text, parse_mode=parse_mode),
                    reply_markup=keyboard, **kw
                ), image_path)
            else:
                new_msg = None
                new_msg = await send_photo_resilient(lambda photo, **kw: target_msg.reply_photo(
                    photo=photo, caption=new_text, reply_markup=keyboard, **kw
                ), image_path)
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


def editor_for(cmd):
    field = EDIT_COMMAND_FIELDS[cmd]
    return FIELD_EDITORS.get(cmd) or FIELD_EDITORS.get(field) or _plain_field_editor(field)


async def apply_edit(context, event_id, cmd, value, reply, admin_user, target_msg=None, update=None, editor=None,
                     card_keyboard=None):
    """Edits one field of an event and refreshes everything that shows it.

    Shared by /event_edit_* and the ✏️ Modifica menu of the admin card. `reply(text, parse_mode=None)` answers the
    admin; `target_msg` is the admin card to redraw (if known), with `card_keyboard(event)` as its buttons when given
    (else the card keeps its own); `editor` overrides the one of the command.
    Returns True on success.
    """
    field = EDIT_COMMAND_FIELDS[cmd]
    current_event = get_event(event_id)
    if not current_event:
        await reply(EDIT_EVENT_NOT_FOUND)
        return False

    editor = editor or editor_for(cmd)
    try:
        success = await editor(update, event_id, current_event, value)
    except EditInputError as e:
        await reply(e.reply, parse_mode=e.parse_mode)
        return False

    admin_identifier = describe_user(admin_user)
    if not success:
        logger.warning(f"{admin_identifier} failed to update field '{field}' to '{value}' for event #{event_id}.")
        await reply(EDIT_DB_ERROR)
        return False

    logger.info(f"{admin_identifier} successfully updated field '{field}' to '{value}' for event #{event_id}.")

    event = get_event(event_id)
    if not event:
        await reply(EDIT_EVENT_MISSING_AFTER_UPDATE)
        return False

    if target_msg:
        keyboard = card_keyboard(event) if card_keyboard else None
        await refresh_admin_message(target_msg, event, image_changed=(field == "image_path"), keyboard=keyboard)

    if event['status'] in ['approved', 'cancelled']:
        await update_event_messages(
            context, event_id, event=event, update_image=(field == "image_path"),
            eventbrite_content=field in EVENTBRITE_CONTENT_FIELDS,
        )

    await reply(format_edit_done(field))
    return True
