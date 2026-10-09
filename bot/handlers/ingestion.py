import logging

from telegram import Update
from telegram.ext import ContextTypes

from core import config
from bot.common.auth import admin_only, describe_user
from bot.common.media import download_first_image, download_media_bytes
from bot.common.messages import command_argument, resolve_message
from bot.handlers.albums import buffer_media_group_message, get_media_group_data_from_cache
from bot.handlers.extraction import handle_event_extraction
from bot.state import runtime_state

logger = logging.getLogger(__name__)


def _is_bot_published_post(message):
    if not (message.reply_markup and message.reply_markup.inline_keyboard):
        return False
    return any(
        button.callback_data and button.callback_data.startswith(("book_", "unbook_"))
        for row in message.reply_markup.inline_keyboard
        for button in row
    )


async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if runtime_state.is_paused:
        logger.info("Bot in pausa: messaggio dal canale eventi ignorato.")
        return

    message = update.message or update.channel_post
    if not message:
        return

    logger.info(f"Ricevuto messaggio dal chat_id: {message.chat_id}")

    # Ignore our own messages and our already-published posts to prevent loops
    if message.from_user and message.from_user.is_bot:
        return
    if _is_bot_published_post(message):
        return

    is_public_channel = str(message.chat_id) == str(config.PUBLIC_CHANNEL_ID)

    if message.media_group_id:
        await buffer_media_group_message(message, context, is_public_channel)
        return

    text = message.text or message.caption
    if not text:
        return

    image_bytes = await download_media_bytes(message.photo[-1]) if message.photo else None

    delete_callback = None
    if is_public_channel:
        async def delete_single_message():
            try:
                await message.delete()
            except Exception as e:
                logger.error(f"Errore durante l'eliminazione del messaggio originale: {e}")
        delete_callback = delete_single_message

    await handle_event_extraction(
        text=text,
        image_bytes=image_bytes,
        context=context,
        message_link=None if is_public_channel else message.link,
        telegram_message_id=message.message_id,
        is_manual_trigger=False,
        delete_callback=delete_callback
    )


@admin_only(notify=True)
async def manual_trigger_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/event_process (/ep): text comes from the command, else the replied message, else the album caption."""
    message = resolve_message(update)
    if not message:
        return

    logger.info(f"{describe_user(update.effective_user)} manually triggered event processing (/event_process).")

    target_msg = message.reply_to_message or message
    is_reply = target_msg is not message

    text = command_argument(message) or None
    if not text and is_reply:
        text = target_msg.text or target_msg.caption

    image_bytes = None
    media_group_id = getattr(target_msg, "media_group_id", None)
    if isinstance(media_group_id, str):
        image_bytes, album_caption = await get_media_group_data_from_cache(media_group_id, wait_if_missing=not is_reply)
        text = text or album_caption

    if image_bytes is None:
        image_bytes = await download_first_image(target_msg)

    if not text:
        if is_reply:
            await message.reply_text("Nessun testo trovato nel messaggio o nel comando. Includi il testo o invia una didascalia.")
        else:
            await message.reply_text("Rispondi a un messaggio o fornisci il testo.")
        return

    success = await handle_event_extraction(text, image_bytes, context, target_msg.link, target_msg.message_id, is_manual_trigger=True)
    if success:
        await message.reply_text("Processato il messaggio risposto." if is_reply else "Processato il testo inviato.")
