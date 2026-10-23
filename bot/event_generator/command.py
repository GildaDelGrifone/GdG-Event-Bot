import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.common.auth import admin_only, describe_user
from bot.common.messages import command_argument, resolve_message
from bot.event_generator.pipeline import process_event_generation
from utils.templates.generator import GENERATE_PROGRESS, GENERATE_USAGE, format_generate_result

logger = logging.getLogger(__name__)

USAGE = GENERATE_USAGE


@admin_only(notify=True)
async def event_generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/event_generate in ADMIN_CHAT_ID."""
    msg = resolve_message(update)
    if not msg:
        return

    logger.info(f"{describe_user(update.effective_user)} triggered event generation (/event_generate).")

    prompt_text = command_argument(msg) or None
    if not prompt_text and msg.reply_to_message:
        prompt_text = msg.reply_to_message.text or msg.reply_to_message.caption

    if not prompt_text:
        await msg.reply_text(USAGE, parse_mode="Markdown")
        return

    status_msg = await msg.reply_text(GENERATE_PROGRESS)
    success, result_text = await process_event_generation(prompt_text, context)

    reply = format_generate_result(success, result_text)
    try:
        await status_msg.edit_text(reply)
    except Exception:
        await msg.reply_text(reply)
