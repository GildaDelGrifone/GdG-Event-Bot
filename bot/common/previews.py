import logging

from core import config
from core.ai_parser import GEMINI_DEPLETED_ALERT
from utils.date_utils import validate_event_date_anomalies
from utils.templates.approval import format_caption_limit_warning, format_date_anomaly_warning
from bot.common.messages import CAPTION_LIMIT, truncate_caption, with_html_fallback

logger = logging.getLogger(__name__)


def date_anomaly_warning(event, raw_text=None):
    warnings = validate_event_date_anomalies(event, raw_text=raw_text)
    if not warnings:
        return ""
    return format_date_anomaly_warning(warnings)


def build_admin_warning_block(event, final_text, has_image, raw_text=None, check_date_anomalies=True):
    block = date_anomaly_warning(event, raw_text=raw_text) if check_date_anomalies else ""
    if has_image and len(final_text) > CAPTION_LIMIT:
        block = format_caption_limit_warning(len(final_text), CAPTION_LIMIT) + block
    return block


async def send_admin_preview(bot, text, image_path, keyboard):
    """Sends an event approval card to ADMIN_CHAT_ID (photo caption when an image exists, truncated to fit)."""
    if image_path:
        caption = truncate_caption(text)
        with open(image_path, 'rb') as f:
            return await with_html_fallback(lambda **kw: bot.send_photo(
                chat_id=config.ADMIN_CHAT_ID, photo=f, caption=caption, reply_markup=keyboard, **kw
            ))
    return await with_html_fallback(lambda **kw: bot.send_message(
        chat_id=config.ADMIN_CHAT_ID, text=text, reply_markup=keyboard, **kw
    ))


async def notify_quota_depleted(bot, chat_id, err, operation):
    logger.error(f"Gemini quota depleted during {operation}: {err}")
    try:
        await bot.send_message(chat_id=chat_id, text=GEMINI_DEPLETED_ALERT)
    except Exception as send_err:
        logger.error(f"Failed to send quota alert to admin: {send_err}")
