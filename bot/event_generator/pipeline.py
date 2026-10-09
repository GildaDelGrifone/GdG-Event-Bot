import logging
import os

from telegram.ext import ContextTypes

from core import config
from core.ai_parser import GeminiQuotaError
from core.db import insert_event, update_event_field
from utils.image_utils import create_collage_from_bytes, save_image_locally
from utils.templates import format_public_event_message
from bot.common.messages import CAPTION_LIMIT
from bot.common.previews import date_anomaly_warning, notify_quota_depleted, send_admin_preview
from bot.event_generator.ai import generate_event_data_with_ai
from bot.event_generator.bgg import fetch_bgg_game_image
from bot.keyboards import get_approval_keyboard

logger = logging.getLogger(__name__)


def enforce_caption_limit(event_data: dict, max_length: int = CAPTION_LIMIT) -> str:
    """Formats the public post, trimming event_data['description'] until it fits max_length."""
    formatted = format_public_event_message(event_data)
    if len(formatted) <= max_length:
        return formatted

    desc = event_data.get("description", "")
    # 5 extra characters leave room for the ellipsis
    trim_amount = len(formatted) - max_length + 5
    event_data["description"] = desc[:-trim_amount].rstrip() + "..." if len(desc) > trim_amount else ""
    formatted = format_public_event_message(event_data)

    if len(formatted) > max_length:
        event_data["description"] = ""
        formatted = format_public_event_message(event_data)
    return formatted


def _save_event_image(games, images, normalized_date):
    """Collages only when several games were requested and several covers were found."""
    if not images:
        return None
    if len(games) > 1 and len(images) > 1:
        collage_bytes = create_collage_from_bytes(images)
        return save_image_locally(collage_bytes, config.DATA_DIR, normalized_date) if collage_bytes else None
    return save_image_locally(images[0], config.DATA_DIR, normalized_date)


async def _send_generated_preview(bot, warning_block, final_text, image_path, keyboard):
    photo_path = image_path if image_path and os.path.exists(image_path) else None
    display_text = warning_block + final_text
    if photo_path and len(display_text) > CAPTION_LIMIT:
        # Keep the full post in the caption; the warnings go in their own message
        if warning_block:
            try:
                await bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=warning_block.strip())
            except Exception as e:
                logger.error(f"Error sending date warning message: {e}")
        display_text = final_text
    return await send_admin_preview(bot, display_text, photo_path, keyboard)


async def process_event_generation(prompt_text: str, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str]:
    """AI fields -> BoardGameGeek covers -> caption-safe post -> pending DB row -> admin approval card."""
    try:
        event_data = generate_event_data_with_ai(prompt_text)
    except GeminiQuotaError as e:
        await notify_quota_depleted(context.bot, config.ADMIN_CHAT_ID, e, "/event_generate")
        return False, "Crediti Gemini AI esauriti. Impossibile generare l'evento."

    if not event_data:
        return False, "Impossibile interpretare l'evento con l'AI. Verifica il messaggio fornito."

    games = event_data.get("games", [])
    images = [img for img in (fetch_bgg_game_image(game) for game in games) if img]
    image_path = _save_event_image(games, images, event_data.get("normalized_date"))

    final_text = enforce_caption_limit(event_data, max_length=CAPTION_LIMIT)

    event_id = insert_event(event_data, image_path, original_text=prompt_text)
    if not event_id:
        logger.error("Failed to insert generated event into DB.")
        return False, "Errore durante il salvataggio dell'evento nel database."

    warning_block = date_anomaly_warning(event_data, raw_text=prompt_text)
    admin_msg = await _send_generated_preview(context.bot, warning_block, final_text, image_path, get_approval_keyboard(event_id))
    if admin_msg:
        update_event_field(event_id, "admin_message_id", admin_msg.message_id)

    return True, "Evento generato con successo e inviato in revisione."
