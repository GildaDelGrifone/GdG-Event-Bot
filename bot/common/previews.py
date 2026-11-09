import logging

from core import config
from core.ai_parser import GEMINI_DEPLETED_ALERT
from utils.date_utils import validate_event_date_anomalies
from utils.templates.approval import format_caption_limit_warning, format_date_anomaly_warning
from telegram.error import BadRequest, NetworkError

from utils.templates.approval import PREVIEW_IMAGE_NOT_DELIVERED
from bot.common.media import send_photo_resilient
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
        try:
            return await send_photo_resilient(lambda photo, **kw: bot.send_photo(
                chat_id=config.ADMIN_CHAT_ID, photo=photo, caption=caption, reply_markup=keyboard, **kw
            ), image_path)
        except NetworkError as e:
            if isinstance(e, BadRequest):
                raise
            # Keep the card usable: the admin can still approve, publishing sends the image again
            logger.error(f"Approval card photo not delivered ({e}), sending the card as text")
            text = PREVIEW_IMAGE_NOT_DELIVERED + text
    return await with_html_fallback(lambda **kw: bot.send_message(
        chat_id=config.ADMIN_CHAT_ID, text=text, reply_markup=keyboard, **kw
    ))


async def notify_quota_depleted(bot, chat_id, err, operation):
    logger.error(f"Gemini quota depleted during {operation}: {err}")
    try:
        await bot.send_message(chat_id=chat_id, text=GEMINI_DEPLETED_ALERT)
    except Exception as send_err:
        logger.error(f"Failed to send quota alert to admin: {send_err}")
