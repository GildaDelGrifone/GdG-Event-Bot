import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.common.auth import admin_only, describe_user
from bot.common.messages import command_argument, resolve_message
from bot.common.parsing import extract_event_id_from_reply
from bot.service.eventbrite import publish_event_to_eventbrite
from core.db import get_event

logger = logging.getLogger(__name__)


@admin_only()
async def event_publish_eventbrite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Same as the [🎟️ Pubblica su Eventbrite] button; every other check lives in publish_event_to_eventbrite."""
    msg = resolve_message(update)
    if not msg:
        return

    reply_msg = msg.reply_to_message
    event_id = extract_event_id_from_reply(reply_msg) if reply_msg else None
    if not event_id:
        arg = command_argument(msg)
        if arg and arg.strip().isdigit():
            event_id = int(arg.strip())

    if not event_id:
        await msg.reply_text(
            "❌ Rispondi al messaggio di un evento (quello con i pulsanti) oppure usa: /event_publish_eventbrite <id>"
        )
        return

    event = get_event(event_id)
    if not event:
        await msg.reply_text(f"❌ Evento #{event_id} non trovato")
        return
    if event.get('status') == 'pending':
        await msg.reply_text("❌ Pubblica prima l'evento su Telegram (oppure usa 🚀 Publish + Eventbrite sulla scheda)")
        return
    if event.get('status') == 'cancelled':
        await msg.reply_text("❌ Evento annullato: riattivalo prima")
        return

    logger.info(f"{describe_user(update.effective_user)} requested Eventbrite publication of event #{event_id}.")
    await publish_event_to_eventbrite(context, event_id, msg.chat_id)
