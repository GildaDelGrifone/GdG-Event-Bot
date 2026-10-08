import logging
from datetime import datetime

from core import config
from core.db import get_pending_events_for_recap, mark_events_as_recap
from utils.date_utils import DAYS_IT
from utils.image_utils import create_collage, compress_existing_image_file
from utils.templates import recap_generate_text
from bot.keyboards import get_recap_approval_keyboard

logger = logging.getLogger(__name__)

RECAP_WEEKDAYS = frozenset({0, 2, 4, 5, 6})  # Mon, Wed, Fri, Sat, Sun game nights
CAPTION_LIMIT = 1024


def _recap_day(manual_date, now):
    if manual_date:
        try:
            return datetime.strptime(manual_date, "%d-%m-%Y")
        except Exception:
            pass
    return now


async def _notify_no_events(bot, date_str, manual_date, now, reply_to_message_id):
    if manual_date and manual_date != now.strftime("%d-%m-%Y"):
        msg = f"Nessun evento in programma per la data {date_str}."
    else:
        msg = "Nessun evento in programma per oggi."
    if reply_to_message_id:
        try:
            await bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=msg, reply_to_message_id=reply_to_message_id)
            return
        except Exception as e:
            logger.warning(f"Failed to reply with reply_to_message_id {reply_to_message_id}: {e}")
    await bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=msg)


def _is_photo_size_error(err):
    err_str = str(err).lower()
    return "photo_invalid_dimensions" in err_str or "dimensions" in err_str or "too large" in err_str


async def _send_collage(bot, collage_path, caption, keyboard):
    """Sends the collage card, retrying once with a recompressed image if Telegram rejects its size."""
    async def send(path):
        with open(path, 'rb') as f:
            await bot.send_photo(chat_id=config.ADMIN_CHAT_ID, photo=f, caption=caption, reply_markup=keyboard, parse_mode="HTML")

    try:
        await send(collage_path)
        return True
    except Exception as e:
        logger.error(f"Error sending recap collage photo to admin: {e}")
        if not _is_photo_size_error(e):
            return False

    try:
        logger.info("Attempting emergency recompression of recap collage...")
        fallback_path = compress_existing_image_file(collage_path, max_dim_sum=5000, max_single_dim=3000, target_max_bytes=1_000_000)
        if fallback_path:
            await send(fallback_path)
            return True
    except Exception as retry_err:
        logger.error(f"Error sending emergency re-compressed recap collage photo: {retry_err}")
    return False


async def generate_daily_recap(bot, manual_date=None, is_manual=False, reply_to_message_id=None):
    """Builds the recap collage + text for a game night and sends it to ADMIN_CHAT_ID for approval."""
    now = datetime.now()
    if not is_manual and now.weekday() not in RECAP_WEEKDAYS:
        return False

    date_str = manual_date or now.strftime("%d-%m-%Y")
    day_str = DAYS_IT[_recap_day(manual_date, now).weekday()]

    logger.info(f"Scheduler: Generating daily recap (manual={is_manual}, date={date_str})...")
    events = get_pending_events_for_recap(date_str)
    if not events:
        logger.info(f"No events pending for recap on {date_str}.")
        if is_manual and bot:
            await _notify_no_events(bot, date_str, manual_date, now, reply_to_message_id)
        return False

    caption_text = recap_generate_text(day_str, date_str, events)[:CAPTION_LIMIT]
    collage_path = create_collage([ev['image_path'] for ev in events if ev['image_path']], config.DATA_DIR, date_str)
    keyboard = get_recap_approval_keyboard(date_str)

    if not (collage_path and await _send_collage(bot, collage_path, caption_text, keyboard)):
        await bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=caption_text, reply_markup=keyboard, parse_mode="HTML")

    # Flag the events so the next automatic recap doesn't pick them up again before approval
    mark_events_as_recap([ev['id'] for ev in events])
    logger.info(f"Scheduler: Daily recap successfully generated and sent to admin for date {date_str} ({len(events)} events).")
    return True
