import logging

from core import config
from core.ai_parser import parse_event_message, GeminiQuotaError
from core.db import insert_event, update_event_field
from utils.date_utils import parse_user_date, format_standard_event_date
from utils.image_utils import save_image_locally
from utils.templates import format_public_event_message
from bot.common.parsing import UNLIMITED_SEATS_DISPLAY, contains_event_keywords, parse_seats_input
from bot.common.previews import build_admin_warning_block, notify_quota_depleted, send_admin_preview
from bot.keyboards import get_approval_keyboard

logger = logging.getLogger(__name__)


def apply_extraction_overrides(event_data, override_date=None, override_seats=None):
    if override_date:
        parsed = parse_user_date(override_date)
        if parsed:
            formatted_date, norm_date = format_standard_event_date(*parsed)
            event_data['date'] = formatted_date
            event_data['normalized_date'] = norm_date

    if override_seats:
        try:
            seats = parse_seats_input(override_seats)
        except ValueError:
            pass
        else:
            if seats is None:
                event_data['max_seats'] = None
                event_data['seats'] = UNLIMITED_SEATS_DISPLAY
            else:
                free, total = seats
                free = total if free is None else free
                event_data['max_seats'] = total
                event_data['seats'] = f"{free}/{total}"
        event_data['booked_seats'] = 0


async def _send_original_text_to_admin(context, text):
    orig_msg = f"📥 Testo originale del messaggio:\n\n{text}"
    if len(orig_msg) > 4000:
        orig_msg = orig_msg[:3990] + "..."
    try:
        await context.bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=orig_msg)
    except Exception as e:
        logger.error(f"Error sending original text to admin: {e}")


async def handle_event_extraction(text, image_bytes, context, message_link=None, telegram_message_id=None, is_manual_trigger=False, delete_callback=None, override_date=None, override_seats=None):
    """AI-parses an announcement, stores it as pending and sends the approval card to ADMIN_CHAT_ID."""
    if not text:
        return False

    if not is_manual_trigger and not contains_event_keywords(text):
        logger.info("Message does not contain any event keywords. Skipping AI extraction.")
        return False

    try:
        event_data = parse_event_message(text)
    except GeminiQuotaError as e:
        await notify_quota_depleted(context.bot, config.ADMIN_CHAT_ID, e, "event extraction")
        return False

    if not event_data or event_data.get('is_event') is False:
        logger.info("Message is not an event or could not be parsed.")
        return False

    apply_extraction_overrides(event_data, override_date, override_seats)

    if delete_callback:
        try:
            await delete_callback()
        except Exception as e:
            logger.error(f"Errore durante l'eliminazione del messaggio originale: {e}")

    image_path = save_image_locally(image_bytes, config.DATA_DIR, event_data.get('normalized_date')) if image_bytes else None

    event_id = insert_event(event_data, image_path, text, message_link, telegram_message_id)
    if not event_id:
        logger.error("Failed to insert event into DB.")
        return False

    # Original text is only useful for channel interceptions; manual triggers already show it in the admin chat
    if not is_manual_trigger:
        await _send_original_text_to_admin(context, text)

    final_text = format_public_event_message(event_data)
    warning_block = build_admin_warning_block(event_data, final_text, has_image=bool(image_path), raw_text=text)
    admin_msg = await send_admin_preview(context.bot, warning_block + final_text, image_path, get_approval_keyboard(event_id))

    if admin_msg:
        update_event_field(event_id, "admin_message_id", admin_msg.message_id)

    return True
