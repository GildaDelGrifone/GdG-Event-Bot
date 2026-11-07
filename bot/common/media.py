import asyncio
import logging
import os
import uuid

from telegram.error import BadRequest

from core import config
from core.astro import delete_media, r2_configured, upload_media
from bot.common.messages import with_html_fallback

logger = logging.getLogger(__name__)

PHOTO_UPLOAD_WRITE_TIMEOUT = 60
TEMP_R2_PREFIX = "telegram-tmp"


def image_media_candidates(msg):
    """Largest photo size first, then an image document, as attached to msg."""
    candidates = []
    photo = getattr(msg, "photo", None)
    if photo and isinstance(photo, (list, tuple)) and len(photo) > 0:
        candidates.append(photo[-1])
    doc = getattr(msg, "document", None)
    if doc and getattr(doc, "mime_type", "").startswith("image/"):
        candidates.append(doc)
    return candidates


async def download_media_bytes(media):
    try:
        tg_file = await media.get_file()
        return await tg_file.download_as_bytearray()
    except Exception as e:
        logger.error(f"Error downloading media: {e}")
        return None


async def download_first_image(msg):
    for media in image_media_candidates(msg):
        image_bytes = await download_media_bytes(media)
        if image_bytes:
            return image_bytes
    return None


def read_image_file(path):
    try:
        with open(path, "rb") as f:
            return bytearray(f.read())
    except Exception as e:
        logger.warning(f"Failed to read image {path}: {e}")
        return None


async def send_photo_resilient(call, image_path, html=True):
    """Sends a local image through call(photo, **kw) (a send_photo / reply_photo / edit_media wrapper).

    By default the file is uploaded directly. With TELEGRAM_PHOTOS_VIA_R2 on (and R2 configured) the image
    goes to the bucket under a temporary key and Telegram gets its public URL, so Telegram downloads it
    itself and nothing is uploaded from here: a workaround for direct uploads that time out while still
    being delivered (duplicate cards). The R2 object is deleted right after the call (Telegram keeps its
    own copy). The direct upload is the fallback when the R2 upload fails or Telegram refuses the URL
    (BadRequest). A timeout on the URL send is raised, not retried: the photo may have been delivered.
    With html=True each attempt goes through with_html_fallback (parse_mode="HTML", plain text on bad markup).
    """
    def attempt(photo, **extra):
        if html:
            return with_html_fallback(lambda **kw: call(photo, **extra, **kw))
        return call(photo, **extra)

    name = os.path.basename(image_path)
    uploaded = None
    if config.TELEGRAM_PHOTOS_VIA_R2 and not r2_configured():
        logger.warning("TELEGRAM_PHOTOS_VIA_R2 is on but R2 is not fully configured: uploading the photo directly")
    elif config.TELEGRAM_PHOTOS_VIA_R2:
        uploaded = await asyncio.to_thread(upload_media, image_path, f"{TEMP_R2_PREFIX}/{uuid.uuid4().hex}")
    if uploaded:
        try:
            result = await attempt(uploaded["source_url"])
            logger.info(f"Photo sent via R2 URL: {name}")
            return result
        except BadRequest as e:
            logger.warning(f"Telegram refused the R2 URL of {name} ({e}), uploading the file instead")
        finally:
            await asyncio.to_thread(delete_media, uploaded["id"])

    with open(image_path, "rb") as f:
        data = f.read()
    result = await attempt(data, write_timeout=PHOTO_UPLOAD_WRITE_TIMEOUT)
    logger.info(f"Photo uploaded to Telegram: {name}")
    return result
