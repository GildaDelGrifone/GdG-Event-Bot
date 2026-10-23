import logging
import os
import re
import uuid

from telegram import Update
from telegram.ext import ContextTypes

from core import config
from core.db import (
    get_event,
    insert_scheduled_event,
    get_scheduled_event,
    get_all_scheduled_events,
    update_scheduled_event_advance_days,
    update_scheduled_event_specific_date,
    update_scheduled_event_content,
)
from core.db.scheduled import MAX_ADVANCE_DAYS
from utils.date_utils import parse_user_date, format_standard_event_date
from utils.templates.common import NO_TEXT_IN_REPLIED_MESSAGE
from utils.templates.reposts import (
    REPOST_UPDATE_REMINDER, SCHEDULE_ADVANCE_UPDATED_PREFIX, SCHEDULE_DATE_UPDATED_PREFIX, SCHEDULE_INVALID_ADVANCE, SCHEDULE_INVALID_DATE, SCHEDULE_INVALID_DATE_FOR_EXISTING,
    SCHEDULE_LIST_EMPTY, SCHEDULE_NO_REPLY, SCHEDULE_SAVE_ERROR, SCHEDULE_UPDATE_ERROR, SCHEDULE_UPDATE_NO_REPLY,
    SCHEDULE_UPDATE_USAGE, format_schedule_list_entry, format_schedule_list_header, format_schedule_repost_message,
    format_scheduled_event_not_found, format_scheduled_event_updated,
)
from bot.common.auth import admin_only, describe_user
from bot.common.messages import command_argument, command_tokens, reply_in_chunks, resolve_message
from bot.common.parsing import extract_event_id_from_reply
from bot.handlers.repost import extract_repost_content
from bot.keyboards import get_schedule_repost_keyboard

logger = logging.getLogger(__name__)


def _save_scheduled_image(image_bytes):
    if not image_bytes:
        return None
    sched_dir = os.path.join(config.DATA_DIR, "scheduled")
    os.makedirs(sched_dir, exist_ok=True)
    path = os.path.join(sched_dir, f"sched_{uuid.uuid4().hex[:8]}.jpg")
    try:
        with open(path, "wb") as f:
            f.write(image_bytes)
        return path
    except Exception as e:
        logger.error(f"Error saving scheduled image: {e}")
        return None


def _scheduled_title(text, target_msg):
    ev_id = extract_event_id_from_reply(target_msg)
    ev = get_event(ev_id) if ev_id else None
    if ev and ev.get('title'):
        return ev['title']
    return text.strip().split("\n")[0][:50]


def _split_advance(tokens):
    """Splits an optional trailing plain integer (the advance days N) off the date tokens: (date_tokens, n or None).

    A bare integer never parses as a date, so "09-10-2026 21:00 2" and "2" are unambiguous.
    """
    if tokens and re.fullmatch(r"-?\d+", tokens[-1]):
        return tokens[:-1], int(tokens[-1])
    return tokens, None


def _valid_advance(days):
    return days is None or 0 <= days <= MAX_ADVANCE_DAYS


async def _reply_schedule_card(message, sched_ev, prefix=""):
    kb = get_schedule_repost_keyboard(sched_ev['id'], sched_ev.get('schedule_days'), sched_ev.get('advance_days'))
    await message.reply_text(prefix + format_schedule_repost_message(sched_ev), reply_markup=kb, parse_mode="HTML")


@admin_only(notify=True)
async def event_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = resolve_message(update)
    if not message:
        return

    args_str = command_argument(message)
    tokens = args_str.split()

    # "/event_schedule <ID> [DATE] [N]" manages an existing schedule
    if tokens and tokens[0].isdigit():
        sched_id = int(tokens[0])
        sched_ev = get_scheduled_event(sched_id)
        if sched_ev:
            if len(tokens) == 1:
                await _reply_schedule_card(message, sched_ev)
                return
            date_tokens, advance = _split_advance(tokens[1:])
            if not _valid_advance(advance):
                await message.reply_text(SCHEDULE_INVALID_ADVANCE)
                return
            prefix = ""
            if date_tokens:
                parsed = parse_user_date(" ".join(date_tokens))
                if not parsed:
                    await message.reply_text(SCHEDULE_INVALID_DATE_FOR_EXISTING)
                    return
                formatted_d, _ = format_standard_event_date(*parsed)
                update_scheduled_event_specific_date(sched_id, formatted_d)
                prefix = SCHEDULE_DATE_UPDATED_PREFIX
            if advance is not None:
                update_scheduled_event_advance_days(sched_id, advance)
                prefix = prefix or SCHEDULE_ADVANCE_UPDATED_PREFIX
            await _reply_schedule_card(message, get_scheduled_event(sched_id), prefix=prefix)
            return

    if not message.reply_to_message:
        await message.reply_text(SCHEDULE_NO_REPLY, parse_mode="HTML")
        return

    text, image_bytes, target_msg = await extract_repost_content(update)
    if not text:
        await message.reply_text(NO_TEXT_IN_REPLIED_MESSAGE)
        return

    date_tokens, advance_days = _split_advance(tokens)
    if not _valid_advance(advance_days):
        await message.reply_text(SCHEDULE_INVALID_ADVANCE)
        return

    specific_date_val = None
    if date_tokens:
        parsed = parse_user_date(" ".join(date_tokens))
        if not parsed:
            await message.reply_text(SCHEDULE_INVALID_DATE)
            return
        specific_date_val, _ = format_standard_event_date(*parsed)

    saved_img_path = _save_scheduled_image(image_bytes)
    scheduled_id = insert_scheduled_event(
        title=_scheduled_title(text, target_msg),
        text=text,
        image_path=saved_img_path,
        schedule_days=[],
        specific_date=specific_date_val,
        advance_days=advance_days or 0,
    )
    if not scheduled_id:
        await message.reply_text(SCHEDULE_SAVE_ERROR)
        return

    msg_text = format_schedule_repost_message(get_scheduled_event(scheduled_id))
    kb = get_schedule_repost_keyboard(scheduled_id, [], advance_days)

    if saved_img_path and os.path.exists(saved_img_path):
        try:
            with open(saved_img_path, "rb") as f:
                await message.reply_photo(photo=f, caption=msg_text, reply_markup=kb, parse_mode="HTML")
                return
        except Exception as e:
            logger.warning(f"Failed to send scheduled event preview photo: {e}")

    await message.reply_text(msg_text, reply_markup=kb, parse_mode="HTML")


@admin_only(notify=True)
async def event_schedule_update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = resolve_message(update)
    if not message:
        return

    if not message.reply_to_message:
        await message.reply_text(SCHEDULE_UPDATE_NO_REPLY, parse_mode="HTML")
        return

    tokens = command_tokens(message)
    if not tokens or not tokens[0].isdigit():
        await message.reply_text(SCHEDULE_UPDATE_USAGE)
        return

    sched_id = int(tokens[0])
    if not get_scheduled_event(sched_id):
        await message.reply_text(format_scheduled_event_not_found(sched_id))
        return

    text, image_bytes, target_msg = await extract_repost_content(update)
    if not text:
        await message.reply_text(NO_TEXT_IN_REPLIED_MESSAGE)
        return

    ok = update_scheduled_event_content(
        sched_id,
        text=text,
        image_path=_save_scheduled_image(image_bytes),
        title=_scheduled_title(text, target_msg),
    )
    if ok:
        await message.reply_text(format_scheduled_event_updated(sched_id), parse_mode="HTML")
    else:
        await message.reply_text(SCHEDULE_UPDATE_ERROR)


@admin_only(notify=True)
async def event_schedule_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = resolve_message(update)
    if not message:
        return

    logger.info(f"{describe_user(update.effective_user)} requested scheduled reposts list (/event_schedule_list).")

    all_events = get_all_scheduled_events()
    if not all_events:
        await message.reply_text(SCHEDULE_LIST_EMPTY)
        return

    lines = [format_schedule_list_header(len(all_events))]
    lines.extend(format_schedule_list_entry(ev) for ev in all_events)
    lines.append(REPOST_UPDATE_REMINDER)

    await reply_in_chunks(message, lines, limit=4000, parse_mode="HTML")
