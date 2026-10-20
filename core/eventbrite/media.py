import logging
import os
import re
import time

import requests
from PIL import Image

from core.eventbrite.client import REQUEST_TIMEOUT, EventbriteError, eb_get, eb_post
from utils.image_utils import pad_to_aspect

logger = logging.getLogger(__name__)

# Eventbrite's WAF sometimes answers the pre-signed upload with an HTML "Whoops!" page (HTTP 429) for the default
# python-requests client, so the upload looks like a normal browser, like the WordPress client does.
BROWSER_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
)
UPLOAD_ATTEMPTS = 3
RETRY_DELAYS = (3, 8)  # seconds before attempt 2 and 3, unless the server sends Retry-After
MAX_RETRY_AFTER = 15
RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})
REASON_MAX_LENGTH = 120


def short_reason(text):
    """A one-line plain-text reason from an error body: an HTML page is reduced to its <title>."""
    text = text or ""
    title = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    if title:
        text = title.group(1)
    else:
        text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    return text if len(text) <= REASON_MAX_LENGTH else text[:REASON_MAX_LENGTH - 1].rstrip() + "…"


def _retry_after(response):
    try:
        return min(float(response.headers.get("Retry-After")), MAX_RETRY_AFTER)
    except (TypeError, ValueError, AttributeError):
        return None


def _upload_once(padded_path, width, height):
    target = eb_get("/media/upload/", params={"type": "image-event-logo"})
    with open(padded_path, "rb") as handle:
        # The upload URL is pre-signed: no Authorization header
        response = requests.post(
            target["upload_url"],
            data=target.get("upload_data") or {},
            files={target["file_parameter_name"]: (os.path.basename(padded_path), handle, "image/jpeg")},
            headers={"User-Agent": BROWSER_USER_AGENT, "Accept": "*/*"},
            timeout=REQUEST_TIMEOUT,
        )
    if not 200 <= response.status_code < 300:
        headers = getattr(response, "headers", None) or {}
        logger.debug(f"Eventbrite logo upload refused ({response.status_code}): "
                     f"Retry-After={headers.get('Retry-After')} Server={headers.get('Server')}")
        error = EventbriteError(response.status_code, "UPLOAD_FAILED", short_reason(response.text))
        error.retry_after = _retry_after(response)
        raise error

    media = eb_post("/media/upload/", json={
        "upload_token": target["upload_token"],
        "crop_mask": {"top_left": {"x": 0, "y": 0}, "width": width, "height": height},
    })
    return media["id"]


def upload_logo(image_path):
    """Uploads the image as an event logo (padded to the required 2:1) and returns the Eventbrite media id.

    The whole upload cycle is retried (with a fresh upload target each time) on rate limits, 5xx and network errors."""
    padded_path = pad_to_aspect(image_path, ratio=2.0, min_size=(2160, 1080))
    try:
        with Image.open(padded_path) as padded:
            width, height = padded.size

        for attempt in range(UPLOAD_ATTEMPTS):
            try:
                return _upload_once(padded_path, width, height)
            except (EventbriteError, requests.ConnectionError, requests.Timeout) as e:
                retryable = isinstance(e, (requests.ConnectionError, requests.Timeout)) or e.status_code in RETRYABLE_STATUSES
                if not retryable or attempt == UPLOAD_ATTEMPTS - 1:
                    raise
                delay = getattr(e, "retry_after", None)
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)] if delay is None else delay
                logger.warning(f"Eventbrite logo upload attempt {attempt + 1}/{UPLOAD_ATTEMPTS} failed ({e}); "
                               f"retrying in {delay:g}s")
                time.sleep(delay)
    finally:
        try:
            os.remove(padded_path)
        except OSError:
            pass
