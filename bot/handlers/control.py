import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.common.auth import admin_only, describe_user
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
async def bot_silent_telegram_toggle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    runtime_state.telegram_silent = not runtime_state.telegram_silent
    state = "ON" if runtime_state.telegram_silent else "OFF"
    logger.info(f"{describe_user(update.effective_user)} turned Telegram silent mode {state}.")
    if runtime_state.telegram_silent:
        text = ("🔇 Modalità silenziosa ATTIVA: gli eventi approvati non vengono pubblicati su Telegram "
                "(usa Eventbrite per pubblicarli). Gli eventi già pubblicati continuano a funzionare.")
    else:
        text = "🔔 Modalità silenziosa DISATTIVATA: gli eventi approvati vengono di nuovo pubblicati su Telegram."
    await update.message.reply_text(text)


@admin_only()
async def bot_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"{describe_user(update.effective_user)} requested bot status.")
    status = "🔴 IN PAUSA (monitoraggio canale eventi disattivato)" if runtime_state.is_paused else "🟢 ATTIVO (monitoraggio canale eventi funzionante)"
    silent = "🔇 SILENZIOSA (gli eventi approvati non vanno su Telegram)" if runtime_state.telegram_silent else "🔔 normale"
    await update.message.reply_text(f"Stato del bot: {status}\nPubblicazione su Telegram: {silent}")
