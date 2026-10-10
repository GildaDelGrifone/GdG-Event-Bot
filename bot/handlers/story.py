import html
import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

from bot.common.auth import admin_only, describe_user
from bot.common.messages import command_argument, resolve_message, send_image_or_error
from bot.common.parsing import extract_event_id_from_reply
from core import config
from core.db import get_event
from utils.image_utils import create_story_image

logger = logging.getLogger(__name__)


@admin_only()
async def event_regenerate_story_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            "❌ Rispondi al messaggio di un evento (quello con i pulsanti) per rigenerarne la storia,\n"
            "oppure usa: /event_regenerate_story <id>"
        )
        return

    event = get_event(event_id)
    if not event:
        await msg.reply_text(f"❌ Evento #{event_id} non trovato nel database.")
        return

    logger.info(f"{describe_user(update.effective_user)} requested story regeneration for event #{event_id}.")
    status_msg = await msg.reply_text("⏳ Rigenerazione Storia Instagram in corso...")

    story_image_path = create_story_image(event, event.get('image_path'), config.DATA_DIR)
    if story_image_path:
        await send_image_or_error(
            context.bot,
            msg.chat_id,
            story_image_path,
            caption=f"✅ Immagine Storia rigenerata per l'evento #{event_id} ({event.get('title') or 'Senza Titolo'}).",
            error_text="❌ Errore durante l'invio dell'immagine della storia.",
        )
        try:
            await status_msg.delete()
        except Exception:
            pass
    else:
        try:
            await status_msg.edit_text("❌ Errore durante la generazione dell'immagine della storia.")
        except Exception:
            await msg.reply_text("❌ Errore durante la generazione dell'immagine della storia.")
