import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.common.auth import admin_only, describe_user
from core.eventbrite import eventbrite_enabled
from bot.state import runtime_state

logger = logging.getLogger(__name__)


@admin_only()
async def bot_pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    runtime_state.is_paused = True
    logger.info(f"{describe_user(update.effective_user)} paused bot execution.")
    await update.message.reply_text("🔴 **Bot in pausa!**\nIl bot ora ignorerà tutti i messaggi inviati sul canale eventi.", parse_mode="Markdown")


@admin_only()
async def bot_resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    runtime_state.is_paused = False
    logger.info(f"{describe_user(update.effective_user)} resumed bot execution.")
    await update.message.reply_text("🟢 **Bot riattivato!**\nIl bot ricomincerà a monitorare il canale eventi.", parse_mode="Markdown")


@admin_only()
async def bot_eventbrite_only_toggle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eventbrite_enabled():
        await update.message.reply_text("❌ Eventbrite non è configurato: la modalità solo Eventbrite non è disponibile.")
        return
    runtime_state.eventbrite_only = not runtime_state.eventbrite_only
    state = "ON" if runtime_state.eventbrite_only else "OFF"
    logger.info(f"{describe_user(update.effective_user)} turned Eventbrite-only mode {state}.")
    if runtime_state.eventbrite_only:
        text = ("🎟️ Modalità solo Eventbrite ATTIVA: la scheda dei nuovi eventi mostra solo i pulsanti Eventbrite "
                "e la storia Instagram non viene generata.")
    else:
        text = "📣 Modalità solo Eventbrite DISATTIVATA: pulsanti Telegram e storia Instagram di nuovo attivi."
    await update.message.reply_text(text)


@admin_only()
async def bot_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"{describe_user(update.effective_user)} requested bot status.")
    status = "🔴 IN PAUSA (monitoraggio canale eventi disattivato)" if runtime_state.is_paused else "🟢 ATTIVO (monitoraggio canale eventi funzionante)"
    mode = "🎟️ SOLO EVENTBRITE (nessun pulsante Telegram, niente storia Instagram)" if runtime_state.eventbrite_only else "📣 normale"
    await update.message.reply_text(f"Stato del bot: {status}\nModalità pubblicazione: {mode}")
