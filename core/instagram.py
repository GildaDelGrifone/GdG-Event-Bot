import asyncio
import logging

import requests

from core import config

logger = logging.getLogger(__name__)

GRAPH_API_URL = "https://graph.facebook.com/v20.0"
REQUEST_TIMEOUT = 30
CONTAINER_PROCESSING_DELAY = 5  # seconds Meta needs to process the image container before publishing


async def _graph_post(endpoint, payload):
    # requests is blocking; keep it off the bot's event loop
    response = await asyncio.to_thread(
        requests.post,
        f"{GRAPH_API_URL}/{config.IG_ACCOUNT_ID}/{endpoint}",
        data={**payload, 'access_token': config.IG_ACCESS_TOKEN},
        timeout=REQUEST_TIMEOUT,
    )
    return response.json()


def _graph_error(resp_json):
    return resp_json.get('error', {}).get('message', 'Sconosciuto')


async def publish_instagram_story(image_url):
    """Publishes a public image URL as an Instagram story; returns (success, message for admins)."""
    if not config.IG_ACCESS_TOKEN or not config.IG_ACCOUNT_ID:
        logger.warning("Instagram credentials not fully configured.")
        return False, "Credenziali Instagram non configurate."

    logger.info(f"Instagram: Starting story publication for image '{image_url}'...")
    try:
        container = await _graph_post("media", {'image_url': image_url, 'media_type': 'STORIES'})
        if 'id' not in container:
            logger.error(f"IG Create Container Failed: {container}")
            return False, f"Errore creazione container IG: {_graph_error(container)}"
        logger.info(f"IG Container created with ID: {container['id']}")

        await asyncio.sleep(CONTAINER_PROCESSING_DELAY)

        published = await _graph_post("media_publish", {'creation_id': container['id']})
        if 'id' not in published:
            logger.error(f"IG Publish Media Failed: {published}")
            return False, f"Errore pubblicazione IG: {_graph_error(published)}"

        logger.info(f"IG Story published successfully with ID: {published['id']}")
        return True, "Storia pubblicata con successo!"
    except Exception as e:
        logger.error(f"Exception during IG Publish: {e}")
        return False, f"Eccezione durante la pubblicazione: {e}"
