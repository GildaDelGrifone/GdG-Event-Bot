import os

import requests
from PIL import Image

from core.eventbrite.client import REQUEST_TIMEOUT, EventbriteError, eb_get, eb_post
from utils.image_utils import pad_to_aspect


def upload_logo(image_path):
    """Uploads the image as an event logo (padded to the required 2:1) and returns the Eventbrite media id."""
    padded_path = pad_to_aspect(image_path, ratio=2.0, min_size=(2160, 1080))
    try:
        with Image.open(padded_path) as padded:
            width, height = padded.size

        target = eb_get("/media/upload/", params={"type": "image-event-logo"})
        with open(padded_path, "rb") as handle:
            # The upload URL is pre-signed: no Authorization header
            response = requests.post(
                target["upload_url"],
                data=target.get("upload_data") or {},
                files={target["file_parameter_name"]: (os.path.basename(padded_path), handle, "image/jpeg")},
                timeout=REQUEST_TIMEOUT,
            )
        if not 200 <= response.status_code < 300:
            raise EventbriteError(response.status_code, "UPLOAD_FAILED", (response.text or "")[:200])

        media = eb_post("/media/upload/", json={
            "upload_token": target["upload_token"],
            "crop_mask": {"top_left": {"x": 0, "y": 0}, "width": width, "height": height},
        })
        return media["id"]
    finally:
        try:
            os.remove(padded_path)
        except OSError:
            pass
