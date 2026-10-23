import html
import logging
import re
from datetime import date

from telegram import Update
from telegram.ext import ContextTypes

from core import config
from core.db import get_event, get_reservations_for_event, get_upcoming_events
from utils.templates.event import format_event_seats
from utils.templates.public import (
    EVENT_NEXT_CANCELLED_SUFFIX, EVENT_NEXT_DATE_PAST, EVENT_NEXT_INVALID_DATE, EVENT_NEXT_NONE,
    EVENT_NEXT_PENDING_SUFFIX, EVENT_REMOVED, EVENT_SUBS_INVALID_ID, EVENT_SUBS_USAGE, START_INVALID_ID,
    START_WELCOME, format_event_next_entry, format_event_next_none_for_day, format_event_next_prefix,
    format_event_next_subscribers_link,
)
from utils.templates.subscribers import format_event_participants_message
from utils.date_utils import DAYS_IT, event_date_tuple, parse_day_filter
from bot.common.auth import describe_user, is_admin_chat
from bot.common.messages import private_chat_link, reply_in_chunks, resolve_message

logger = logging.getLogger(__name__)


def _format_event_next_entry(ev, bot_username):
    ev_id = ev['id']
    escaped_title = html.escape(ev.get('title') or 'Senza Titolo')
    escaped_date = html.escape(ev.get('date') or ev.get('normalized_date') or 'N/A')

    status_suffix = ""
    if ev.get('status') == 'pending':
        status_suffix = EVENT_NEXT_PENDING_SUFFIX
    elif ev.get('status') == 'cancelled':
        status_suffix = EVENT_NEXT_CANCELLED_SUFFIX

    links = []
    if ev.get('admin_message_id'):
        links.append(private_chat_link(config.ADMIN_CHAT_ID, ev['admin_message_id'], "Admin", "Admin msg"))

    disc_msg_id = ev.get('discussion_message_id')
    disc_chat = ev.get('discussion_chat_id') or config.DISCUSSION_GROUP_ID or ''
    if disc_msg_id and str(disc_chat):
        links.append(private_chat_link(disc_chat, disc_msg_id, "Chat Discussione", "Chat msg"))

    if ev.get('message_link'):
        links.append(f'<a href="{ev["message_link"]}">Canale Eventi</a>')

    links.append(format_event_next_subscribers_link(format_event_seats(ev), bot_username, ev_id))

    return format_event_next_entry(ev_id, escaped_title, status_suffix, escaped_date, links)


def _day_argument(message):
    """The date typed after /event_next (or /event_next@bot); "" otherwise, e.g. for the /start event_next deep link."""
    parts = (message.text or "").split(maxsplit=1)
    if not parts or parts[0].split("@")[0].lower() != "/event_next":
        return ""
    return parts[1].strip() if len(parts) > 1 else ""


async def event_next_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = resolve_message(update)
    if not message or not update.effective_chat:
        return

    chat = update.effective_chat
    chat_id_str = str(chat.id)
    chat_type = getattr(chat, "type", "")

    is_admin = is_admin_chat(update)
    is_discussion_group = bool(config.DISCUSSION_GROUP_ID and chat_id_str == str(config.DISCUSSION_GROUP_ID))
    is_private_chat = chat_type == "private"

    if not (is_admin or is_private_chat or is_discussion_group):
        return
    if is_discussion_group and not is_admin and not config.ALLOW_GROUP_EVENT_NEXT:
        return

    logger.info(f"{describe_user(update.effective_user, role='User')} requested upcoming events (/event_next) in chat {chat_id_str} ({chat_type}).")

    day = None
    day_text = _day_argument(message)
    if day_text:
        day = parse_day_filter(day_text)
        if day is None:
            await message.reply_text(EVENT_NEXT_INVALID_DATE)
            return
        if day < date.today():
            await message.reply_text(EVENT_NEXT_DATE_PAST)
            return

    events = get_upcoming_events(include_today=True)
    if day:
        events = [ev for ev in events if event_date_tuple(ev) == (day.year, day.month, day.day)]
    day_label = f"{DAYS_IT[day.weekday()]} {day.strftime('%d-%m-%Y')}" if day else ""
    if not events:
        await message.reply_text(format_event_next_none_for_day(day_label) if day else EVENT_NEXT_NONE)
        return

    bot_username = getattr(getattr(context, 'bot', None), 'username', None) or config.TELEGRAM_BOT_USERNAME
    await reply_in_chunks(
        message,
        [_format_event_next_entry(ev, bot_username) for ev in events],
        limit=3800,
        prefix=format_event_next_prefix(day_label),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def _reply_with_participants(message, event_id):
    event = get_event(event_id)
    if not event:
        await message.reply_text(EVENT_REMOVED)
        return
    text = format_event_participants_message(event, get_reservations_for_event(event_id))
    await message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def event_subs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = resolve_message(update)
    if not message:
        return

    event_id_str = None
    if context.args:
        event_id_str = context.args[0]
    else:
        text = (message.text or message.caption or "").strip()
        m = re.match(r"^/(?:event_subs|subs)(?:_|\s+)(\d+)", text, re.IGNORECASE)
        if m:
            event_id_str = m.group(1)

    if not event_id_str:
        await message.reply_text(EVENT_SUBS_USAGE)
        return

    try:
        event_id = int(event_id_str)
    except ValueError:
        await message.reply_text(EVENT_SUBS_INVALID_ID)
        return

    await _reply_with_participants(message, event_id)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = resolve_message(update)
    if not message:
        return

    arg = context.args[0] if context.args else None
    if arg == "event_next":
        await event_next_command(update, context)
        return
    if arg and arg.startswith("subs_"):
        try:
            event_id = int(arg.split("_")[1])
        except (IndexError, ValueError):
            await message.reply_text(START_INVALID_ID)
            return
        await _reply_with_participants(message, event_id)
        return

    await message.reply_text(START_WELCOME)
