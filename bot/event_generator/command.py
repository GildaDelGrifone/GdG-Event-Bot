import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.common.auth import admin_only, describe_user
from bot.common.messages import command_argument, resolve_message
from bot.event_generator.pipeline import process_event_generation

logger = logging.getLogger(__name__)

USAGE = (
    "ℹ️ **Uso del comando /event_generate:**\n"
    "Invia il comando seguito dai dettagli dell'evento, oppure rispondi a un messaggio.\n\n"
    "**Esempi:**\n"
    "`/event_generate Catan e Carcassonne, venerdì 10 ottobre ore 21, Host Destard, 4 posti`\n"
    "`/eg Root, domani alle 20:45, Host Marco`"
)


@admin_only(notify=True)
async def event_generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/event_generate and /eg in ADMIN_CHAT_ID."""
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

    status_msg = await msg.reply_text("⏳ Generazione evento in corso con AI e BoardGameGeek...")
    success, result_text = await process_event_generation(prompt_text, context)

    reply = f"{'✅' if success else '❌'} {result_text}"
    try:
        await status_msg.edit_text(reply)
    except Exception:
        await msg.reply_text(reply)
