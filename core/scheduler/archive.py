import glob
import logging
import os
import zipfile
from datetime import datetime

from core import config
from core.db import get_approved_events_for_date
from core.log_utils import zip_completed_months

logger = logging.getLogger(__name__)

IMAGE_PATTERNS = ("*.jpg", "*.jpeg", "*.png", "*.webp")
_IGNORED_EDIT_ERRORS = ("not modified", "message to edit not found")


def archive_images_in(target_dir):
    """Moves loose images in target_dir into target_dir/archive.zip."""
    if not os.path.exists(target_dir):
        logger.info(f"Archive: No folder found for today ({target_dir}).")
        return

    image_files = [path for pattern in IMAGE_PATTERNS for path in glob.glob(os.path.join(target_dir, pattern))]
    if not image_files:
        logger.info(f"Archive: No image files found in {target_dir} to archive.")
        return

    zip_path = os.path.join(target_dir, "archive.zip")
    logger.info(f"Archive: Zipping {len(image_files)} images into {zip_path}")
    try:
        with zipfile.ZipFile(zip_path, 'a', zipfile.ZIP_DEFLATED) as zipf:
            for img in image_files:
                zipf.write(img, os.path.basename(img))
        for img in image_files:
            try:
                os.remove(img)
            except Exception as e:
                logger.warning(f"Archive: Failed to delete {img}: {e}")
        logger.info(f"Archive: Successfully archived and removed {len(image_files)} images in {target_dir}.")
    except Exception as e:
        logger.error(f"Archive: Error creating zip archive in {target_dir}: {e}")


async def _remove_booking_keyboard(bot, chat_id, message_id, where, event_id):
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        logger.info(f"Scheduler: Removed booking keyboard from {where} for event #{event_id}.")
    except Exception as e:
        if not any(ignored in str(e).lower() for ignored in _IGNORED_EDIT_ERRORS):
            logger.error(f"Scheduler: Error removing booking keyboard in {where} for event #{event_id}: {e}")


async def disable_bookings_for_date(bot, date_str):
    """Strips the booking buttons from the channel post and discussion reply of each approved event on date_str."""
    logger.info("Scheduler: Disabling bookings for today's events...")
    try:
        for ev in get_approved_events_for_date(date_str):
            if config.PUBLIC_CHANNEL_ID and ev.get('telegram_message_id'):
                await _remove_booking_keyboard(bot, config.PUBLIC_CHANNEL_ID, ev['telegram_message_id'], "public channel", ev['id'])

            disc_chat_id = ev.get('discussion_chat_id') or config.DISCUSSION_GROUP_ID
            if disc_chat_id and ev.get('discussion_message_id'):
                await _remove_booking_keyboard(bot, int(disc_chat_id), ev['discussion_message_id'], "discussion group", ev['id'])
    except Exception as e:
        logger.error(f"Scheduler: Error disabling bookings for today's events: {e}")


async def archive_today_images(bot=None):
    """Nightly job: archive today's images and close bookings for today's events."""
    logger.info("Scheduler: Starting archive_today_images job...")
    now = datetime.now()
    archive_images_in(os.path.join(config.DATA_DIR, now.strftime("%Y"), now.strftime("%m"), now.strftime("%d")))
    if bot:
        await disable_bookings_for_date(bot, now.strftime("%d-%m-%Y"))


async def archive_completed_month_logs():
    logger.info("Scheduler: Starting archive_completed_month_logs job...")
    try:
        archived = zip_completed_months(config.LOGS_DIR)
        if archived:
            logger.info(f"Archive: Zipped monthly log files: {archived}")
        else:
            logger.info("Archive: No completed month logs needed archiving.")
    except Exception as e:
        logger.error(f"Archive: Error checking and zipping monthly logs: {e}")
