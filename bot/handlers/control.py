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
async def bot_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"{describe_user(update.effective_user)} requested bot status.")
    status = "🔴 IN PAUSA (monitoraggio canale eventi disattivato)" if runtime_state.is_paused else "🟢 ATTIVO (monitoraggio canale eventi funzionante)"
    await update.message.reply_text(f"Stato del bot: {status}")
