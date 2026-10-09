import logging

logger = logging.getLogger(__name__)


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
