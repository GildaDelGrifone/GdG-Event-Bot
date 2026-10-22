import logging
import os
import re

from telegram import Update
from telegram.ext import ContextTypes

from core.db import get_event, get_scheduled_event
from utils.date_utils import parse_user_date
from bot.common.auth import admin_only, describe_user
from bot.common.media import read_image_file
from bot.common.messages import command_argument, command_tokens, resolve_message
from bot.common.parsing import extract_event_id_from_reply
from bot.handlers.albums import extract_image_bytes_from_update
from bot.handlers.extraction import handle_event_extraction
from utils.templates import (
    NO_TEXT_IN_REPLIED_MESSAGE, REPOST_DONE, REPOST_INVALID_DATE, REPOST_MISSING_PARAMS, REPOST_NO_REPLY, REPOST_USAGE,
    SCHEDULE_INVOKE_USAGE, SCHEDULED_EVENT_NO_TEXT, format_scheduled_event_invoked, format_scheduled_event_not_found,
)

logger = logging.getLogger(__name__)

async def extract_repost_content(update: Update):
    """Returns (text, image_bytes, target_msg), falling back to the stored event when the target is a known event."""
    message = resolve_message(update)
    if not message:
        return None, None, None

    target_msg = message.reply_to_message or message
    text = target_msg.text or target_msg.caption
    image_bytes = await extract_image_bytes_from_update(update)

    ev_id = extract_event_id_from_reply(target_msg)
    ev = get_event(ev_id) if ev_id else None
    if ev:
        if not text:
            text = ev.get('original_text') or ev.get('description')
        if not image_bytes and ev.get('image_path') and os.path.exists(ev['image_path']):
            image_bytes = read_image_file(ev['image_path'])

    return text, image_bytes, target_msg


@admin_only(notify=True)
async def event_repost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = resolve_message(update)
    if not message:
        return

    if not message.reply_to_message:
        await message.reply_text(REPOST_NO_REPLY, parse_mode="HTML")
        return

    tokens = command_argument(message).split()
    if len(tokens) < 2:
        await message.reply_text(REPOST_MISSING_PARAMS, parse_mode="HTML")
        return

    seats_arg = tokens[-1]
    date_arg = " ".join(tokens[:-1])

    if not parse_user_date(date_arg):
        await message.reply_text(REPOST_INVALID_DATE)
        return

    text, image_bytes, target_msg = await extract_repost_content(update)
    if not text:
        await message.reply_text(NO_TEXT_IN_REPLIED_MESSAGE)
        return

    logger.info(f"{describe_user(update.effective_user)} triggered /event_repost with date='{date_arg}', seats='{seats_arg}'.")

    success = await handle_event_extraction(
        text=text,
        image_bytes=image_bytes,
        context=context,
        message_link=getattr(target_msg, "link", None),
        telegram_message_id=getattr(target_msg, "message_id", None),
        is_manual_trigger=True,
        override_date=date_arg,
        override_seats=seats_arg
    )
    if success:
        await message.reply_text(REPOST_DONE)


def _invoke_overrides(sched_ev, extra_tokens):
    """Date defaults to today (keeping any scheduled time); extra tokens are "[DATE...] [SEATS]"."""
    override_date = "oggi"
    spec = sched_ev.get('specific_date')
    m_time = re.search(r'\b(\d{1,2}:\d{2})\b', spec) if spec else None
    if m_time:
        override_date = f"oggi {m_time.group(1)}"

    override_seats = None
    if len(extra_tokens) == 1:
        token = extra_tokens[0]
        if token.isdigit() or "/" in token:
            override_seats = token
        else:
            override_date = token
    elif len(extra_tokens) >= 2:
        override_seats = extra_tokens[-1]
        override_date = " ".join(extra_tokens[:-1])
    return override_date, override_seats


@admin_only(notify=True)
async def event_schedule_invoke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = resolve_message(update)
    if not message:
        return

    tokens = command_tokens(message)
    if not tokens or not tokens[0].isdigit():
        await message.reply_text(SCHEDULE_INVOKE_USAGE)
        return

    sched_id = int(tokens[0])
    sched_ev = get_scheduled_event(sched_id)
    if not sched_ev:
        await message.reply_text(format_scheduled_event_not_found(sched_id))
        return

    text = sched_ev.get('text')
    if not text:
        await message.reply_text(SCHEDULED_EVENT_NO_TEXT)
        return

    img_path = sched_ev.get('image_path')
    image_bytes = read_image_file(img_path) if img_path and os.path.exists(img_path) else None

    override_date, override_seats = _invoke_overrides(sched_ev, tokens[1:])
    success = await handle_event_extraction(
        text=text,
        image_bytes=image_bytes,
        context=context,
        is_manual_trigger=True,
        override_date=override_date,
        override_seats=override_seats
    )
    if success:
        await message.reply_text(format_scheduled_event_invoked(sched_id))
