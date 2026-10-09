"""Buffering of Telegram albums (media groups), which arrive as one update per photo."""
import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from utils.image_utils import create_collage_from_bytes
from bot.common.media import download_first_image, download_media_bytes
from bot.handlers.extraction import handle_event_extraction

logger = logging.getLogger(__name__)

# media_group_id -> buffered album data; mutated in place, never rebound.
media_groups = {}        # albums posted in the public channel, awaiting extraction
admin_media_groups = {}  # albums sent in the admin chat, kept for /ep and /event_edit_image


def _build_collage(images, label):
    if len(images) > 1:
        logger.info(f"Building collage for {label} with {len(images)} images.")
        return create_collage_from_bytes(images) or images[0]
    return images[0] if images else None


def cleanup_admin_media_cache(now=None, max_age_seconds=3600, max_entries=20):
    if now is None:
        now = asyncio.get_event_loop().time()
    expired = [k for k, v in admin_media_groups.items() if now - v.get("last_received", 0) > max_age_seconds]
    for k in expired:
        admin_media_groups.pop(k, None)
    if len(admin_media_groups) > max_entries:
        sorted_keys = sorted(admin_media_groups.keys(), key=lambda k: admin_media_groups[k].get("last_received", 0))
        for k in sorted_keys[:-max_entries]:
            admin_media_groups.pop(k, None)


async def cache_admin_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    msg_photo = getattr(msg, "photo", None)
    msg_doc = getattr(msg, "document", None)
    is_image_doc = msg_doc and getattr(msg_doc, "mime_type", "").startswith("image/")
    if not (msg_photo and isinstance(msg_photo, (list, tuple))) and not is_image_doc:
        return

    media_group_id = getattr(msg, "media_group_id", None)
    if not media_group_id or not isinstance(media_group_id, str):
        return

    now = asyncio.get_event_loop().time()
    cleanup_admin_media_cache(now)

    entry = admin_media_groups.setdefault(media_group_id, {
        "images": {},
        "captions": {},
        "last_received": now,
        "pending_downloads": 0,
    })
    entry["last_received"] = now

    caption = getattr(msg, "caption", None)
    if caption:
        entry["captions"][msg.message_id] = caption

    entry["pending_downloads"] += 1
    try:
        img_bytes = await download_first_image(msg)
        if img_bytes is not None:
            entry["images"][msg.message_id] = img_bytes
    finally:
        entry["pending_downloads"] -= 1


async def get_media_group_data_from_cache(
    media_group_id: str,
    wait_if_missing: bool = True,
    timeout: float = 3.5,
    debounce: float = 1.0,
):
    """Returns (image_bytes, first_caption) for a cached admin album once its downloads have settled."""
    if not media_group_id:
        return None, None

    loop = asyncio.get_event_loop()
    start_wait = loop.time()
    if wait_if_missing:
        while media_group_id not in admin_media_groups:
            if loop.time() - start_wait > timeout:
                return None, None
            await asyncio.sleep(0.1)
    elif media_group_id not in admin_media_groups:
        return None, None

    group_entry = admin_media_groups[media_group_id]
    while loop.time() - start_wait < timeout:
        if group_entry.get("pending_downloads", 0) > 0 or loop.time() - group_entry.get("last_received", 0) < debounce:
            await asyncio.sleep(0.1)
            continue
        break

    images_dict = group_entry.get("images", {})
    cached_images = [images_dict[mid] for mid in sorted(images_dict) if images_dict[mid]]
    image_bytes = _build_collage(cached_images, f"admin media group {media_group_id}") if cached_images else None

    captions = group_entry.get("captions", {})
    first_caption = next((captions[mid] for mid in sorted(captions) if captions[mid]), None)

    return image_bytes, first_caption


async def image_from_message(msg, wait_for_album):
    media_group_id = getattr(msg, "media_group_id", None)
    if isinstance(media_group_id, str):
        cached, _ = await get_media_group_data_from_cache(media_group_id, wait_if_missing=wait_for_album)
        if cached:
            return cached
    return await download_first_image(msg)


async def extract_image_bytes_from_update(update: Update):
    if not update.message:
        return None
    # Media attached to the command itself wins over media in the replied-to message
    image = await image_from_message(update.message, wait_for_album=True)
    if image:
        return image
    if update.message.reply_to_message:
        return await image_from_message(update.message.reply_to_message, wait_for_album=False)
    return None


async def finalize_media_group(media_group_id: str, context: ContextTypes.DEFAULT_TYPE):
    # Wait for 2.0 seconds of silence after the last message of the album
    while True:
        group = media_groups.get(media_group_id)
        if not group:
            return

        elapsed = asyncio.get_event_loop().time() - group.get("last_received", 0)
        if elapsed < 2.0:
            await asyncio.sleep(2.0 - elapsed)
            continue
        if group.get("pending_downloads", 0) > 0:
            await asyncio.sleep(0.2)
            continue
        break

    group = media_groups.pop(media_group_id, None)
    if not group:
        return

    text = group.get("text")
    if not text:
        logger.info(f"Media group {media_group_id} had no text caption. Ignoring.")
        return

    messages = group.get("messages", [])
    delete_callback = None
    if group.get("is_public_channel", False) and messages:
        async def delete_album_messages():
            for msg in messages:
                try:
                    await msg.delete()
                except Exception as e:
                    logger.error(f"Errore durante l'eliminazione del messaggio {getattr(msg, 'message_id', 'unknown')} dell'album: {e}")
        delete_callback = delete_album_messages

    await handle_event_extraction(
        text=text,
        image_bytes=_build_collage(group.get("images", []), "event"),
        context=context,
        message_link=group.get("message_link"),
        telegram_message_id=group.get("message_id"),
        is_manual_trigger=False,
        delete_callback=delete_callback
    )


async def buffer_media_group_message(message, context, is_public_channel):
    media_group_id = message.media_group_id
    now = asyncio.get_event_loop().time()
    group = media_groups.setdefault(media_group_id, {
        "images": [],
        "text": None,
        "message_link": None if is_public_channel else message.link,
        "message_id": message.message_id,
        "messages": [],
        "is_public_channel": is_public_channel,
        "last_received": now,
        "pending_downloads": 0,
        "task": None,
    })
    group["last_received"] = now
    group["messages"].append(message)

    text = message.text or message.caption
    if text and not group["text"]:
        group["text"] = text

    if not is_public_channel and not group["message_link"]:
        group["message_link"] = message.link

    if message.photo:
        group["pending_downloads"] += 1
        try:
            img_bytes = await download_media_bytes(message.photo[-1])
            if img_bytes is not None:
                group["images"].append(img_bytes)
        finally:
            group["pending_downloads"] -= 1

    if group["task"] is None:
        group["task"] = asyncio.create_task(finalize_media_group(media_group_id, context))
