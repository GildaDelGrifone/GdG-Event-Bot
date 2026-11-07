import io
import logging
import mimetypes
import os

import requests
from PIL import Image, ImageOps

from core import config
from core.astro.client import r2_client

logger = logging.getLogger(__name__)

MAX_IMAGE_WIDTH = 1600
HEAD_TIMEOUT = 10
_RESIZABLE = {"image/jpeg": "JPEG", "image/png": "PNG"}


def _prepare_image(filepath):
    """(bytes, content_type) ready for upload; JPEG/PNG are oriented and limited to MAX_IMAGE_WIDTH."""
    content_type, _ = mimetypes.guess_type(filepath)
    content_type = content_type or "application/octet-stream"
    fmt = _RESIZABLE.get(content_type)
    if not fmt:
        with open(filepath, "rb") as f:
            return f.read(), content_type

    with Image.open(filepath) as img:
        img = ImageOps.exif_transpose(img)
        if img.width > MAX_IMAGE_WIDTH:
            img = img.resize((MAX_IMAGE_WIDTH, round(img.height * MAX_IMAGE_WIDTH / img.width)), Image.LANCZOS)
        buf = io.BytesIO()
        if fmt == "JPEG":
            img.convert("RGB").save(buf, format=fmt, quality=85)
        else:
            img.save(buf, format=fmt)
    return buf.getvalue(), content_type


def upload_media(filepath, key_prefix):
    """Uploads a file to R2 as '<key_prefix>/<filename>'; returns {'id': key, 'source_url'} or None."""
    filename = os.path.basename(filepath)
    key = f"{key_prefix.strip('/')}/{filename}"
    try:
        client = r2_client()
        if not client:
            logger.warning("R2 credentials not fully configured for media upload.")
            return None
        logger.info(f"R2: Uploading media file '{filename}' as '{key}'...")
        body, content_type = _prepare_image(filepath)
        client.put_object(Bucket=config.R2_BUCKET, Key=key, Body=body, ContentType=content_type)
        return {"id": key, "source_url": f"{config.R2_PUBLIC_URL}/{key}"}
    except ImportError:
        logger.error("R2: boto3 is not installed; run: pip install -r requirements.txt")
        return None
    except Exception as e:
        logger.error(f"R2: Failed to upload '{filename}': {e}")
        return None


def delete_media(key):
    """Deletes an object of the bucket; logs and returns False on failure, never raises."""
    try:
        client = r2_client()
        if not client:
            return False
        client.delete_object(Bucket=config.R2_BUCKET, Key=key)
        return True
    except Exception as e:
        logger.warning(f"R2: Failed to delete '{key}' (remove it by hand): {e}")
        return False


def media_url(key):
    """The public address of an object of the bucket."""
    return f"{config.R2_PUBLIC_URL}/{key}"


def is_reachable(url):
    """True when a HEAD request on `url` answers 200 (a network error counts as not reachable)."""
    try:
        return requests.head(url, timeout=HEAD_TIMEOUT, allow_redirects=True).status_code == 200
    except requests.RequestException:
        return False


# Plain file transfers to any bucket of the account (no resizing, errors raised): used by the DB backup copies,
# which go to a private bucket, never to the public media bucket.
def _require_client():
    client = r2_client()
    if not client:
        raise RuntimeError("R2 credentials are not configured")
    return client


def upload_file(filepath, key, bucket):
    _require_client().upload_file(filepath, bucket, key)


def download_file(key, filepath, bucket):
    _require_client().download_file(bucket, key, filepath)


def list_keys(prefix, bucket):
    """The keys under `prefix` (all pages)."""
    client = _require_client()
    keys = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys += [item["Key"] for item in page.get("Contents", [])]
    return keys


def delete_key(key, bucket):
    _require_client().delete_object(Bucket=bucket, Key=key)
