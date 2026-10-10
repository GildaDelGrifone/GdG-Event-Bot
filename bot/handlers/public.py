import html
import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from core import config
from core.db import get_event, get_reservations_for_event, get_upcoming_events
from utils.templates import format_event_participants_message, format_event_seats
from bot.common.auth import describe_user, is_admin_chat
from bot.common.messages import private_chat_link, reply_in_chunks, resolve_message

logger = logging.getLogger(__name__)


def _format_event_next_entry(ev, bot_username):
    ev_id = ev['id']
    escaped_title = html.escape(ev.get('title') or 'Senza Titolo')
    escaped_date = html.escape(ev.get('date') or ev.get('normalized_date') or 'N/A')

    status_suffix = ""
    if ev.get('status') == 'pending':
        status_suffix = " <i>[In attesa di approvazione]</i>"
    elif ev.get('status') == 'cancelled':
        status_suffix = " ❌ <i>[ANNULLATO]</i>"

    links = []
    if ev.get('admin_message_id'):
        links.append(private_chat_link(config.ADMIN_CHAT_ID, ev['admin_message_id'], "Admin", "Admin msg"))

    disc_msg_id = ev.get('discussion_message_id')
    disc_chat = ev.get('discussion_chat_id') or config.DISCUSSION_GROUP_ID or ''
    if disc_msg_id and str(disc_chat):
        links.append(private_chat_link(disc_chat, disc_msg_id, "Chat Discussione", "Chat msg"))

    if ev.get('message_link'):
        links.append(f'<a href="{ev["message_link"]}">Canale Eventi</a>')

    seats_str = format_event_seats(ev)
    if bot_username:
        clean_username = bot_username.lstrip('@')
        links.append(f'<a href="https://t.me/{clean_username}?start=subs_{ev_id}">👥 Iscritti</a> ({seats_str})')
    else:
        links.append(f'👥 Iscritti ({seats_str})')

    return (
        f"• <b>{escaped_title}</b> (ID {ev_id}){status_suffix}\n"
        f"  🗓️ Data: {escaped_date}\n"
        f"  🔗 {' | '.join(links)}\n"
    )


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

    events = get_upcoming_events(include_today=True)
    if not events:
        await message.reply_text("Nessun evento in programma per oggi o per i prossimi giorni.")
        return

    bot_username = getattr(getattr(context, 'bot', None), 'username', None) or config.TELEGRAM_BOT_USERNAME
    await reply_in_chunks(
        message,
        [_format_event_next_entry(ev, bot_username) for ev in events],
        limit=3800,
        prefix="📅 <b>Eventi di oggi e prossimi in programma:</b>\n<i>Per visualizzare i partecipanti usa /event_subs &lt;id&gt; oppure clicca su 👥 Iscritti.</i>\n\n",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def _reply_with_participants(message, event_id):
    event = get_event(event_id)
    if not event:
        await message.reply_text("❌ Evento non trovato o già rimosso.")
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
        await message.reply_text("❌ Specifica l'ID dell'evento (es. /event_subs 123 o /subs 123).")
        return

    try:
        event_id = int(event_id_str)
    except ValueError:
        await message.reply_text("❌ ID evento non valido. Deve essere un numero intero.")
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
            await message.reply_text("❌ ID evento non valido.")
            return
        await _reply_with_participants(message, event_id)
        return

    await message.reply_text(
        "👋 Ciao! Sono il bot per la gestione degli eventi della Gilda del Grifone.\n\n"
        "Puoi visualizzare le proposte e gestire le prenotazioni direttamente dai pulsanti interattivi sul canale e nel gruppo di discussione!\n\n"
        "Inoltre puoi visualizzare facilmente gli eventi in programma e i partecipanti con i seguenti comandi:\n"
        "/event_next - Visualizza gli eventi in programma\n"
        "/event_subs <id> - Visualizza i partecipanti a un evento specifico\n"
    )
