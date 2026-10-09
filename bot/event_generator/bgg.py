import html
import logging
import re
import urllib.parse

import requests

from core import config

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "GdG-Event-Bot/1.0 (+https://github.com/destard/GdG-Event-Bot)"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
BGG_SEARCH_URL = "https://api.geekdo.com/api/geekitems?objecttype=thing&search="
BGG_DETAIL_URL = "https://api.geekdo.com/api/geekitems?objecttype=thing&objectid="

ACCESSORY_RE = re.compile(
    r"\b(\d+\s*x\s*\d+\s*mm|sleeves?|enamel|coins?|tokens?|insert|organizer|playmat|dice bag|promo pack|promo card|upgrade kit|goodie|neoprene|custom dice)\b",
    re.I,
)


def pick_best_bgg_item(items, query):
    """Exact name match, else the first non-accessory containing the query, else any non-accessory, else the first item."""
    q_norm = query.lower()
    named = [(item, item.get("name", "").strip()) for item in items]

    for item, name in named:
        if name.lower() == q_norm:
            return item
    for item, name in named:
        if not ACCESSORY_RE.search(name) and q_norm in name.lower():
            return item
    for item, name in named:
        if not ACCESSORY_RE.search(name):
            return item
    return items[0]


def bgg_image_url(item_data):
    """Prefers the high-resolution 'original' image over 'imageurl'."""
    images = item_data.get("images")
    url = images.get("original") if isinstance(images, dict) else None
    url = url or item_data.get("imageurl")
    if url and url.startswith("//"):
        url = "https:" + url
    return url


def fetch_bgg_api_image(game_name: str, token: str | None = None, timeout: int = 10) -> bytes | None:
    """Original BoardGameGeek API lookup. Requires a valid BGG API token if protected."""
    if not game_name or not game_name.strip():
        return None
    q = game_name.strip()
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.get(f"{BGG_SEARCH_URL}{urllib.parse.quote(q)}", headers=headers, timeout=timeout)
        if resp.status_code != 200:
            logger.warning(f"BGG search for '{q}' returned status {resp.status_code}")
            return None

        items = resp.json().get("items", [])
        if not items:
            logger.info(f"No BGG search items found for '{q}'")
            return None

        object_id = pick_best_bgg_item(items, q).get("objectid")
        if not object_id:
            return None

        det_resp = requests.get(f"{BGG_DETAIL_URL}{object_id}", headers=headers, timeout=timeout)
        if det_resp.status_code != 200:
            logger.warning(f"BGG item detail fetch for ID {object_id} returned {det_resp.status_code}")
            return None

        image_url = bgg_image_url(det_resp.json().get("item", {}))
        if not image_url:
            logger.info(f"No image URL found in BGG item for '{q}' (ID: {object_id})")
            return None

        img_resp = requests.get(image_url, headers=headers, timeout=timeout + 5)
        if img_resp.status_code == 200:
            return img_resp.content
        logger.warning(f"Failed to download image from {image_url}: status {img_resp.status_code}")
        return None

    except Exception as e:
        logger.error(f"Error fetching BGG image for '{q}': {e}")
        return None


def fetch_wikipedia_game_image(game_name: str, timeout: int = 10) -> bytes | None:
    """Attempt to fetch board game cover thumbnail from Wikipedia REST API."""
    if not game_name or not game_name.strip():
        return None
    q = game_name.strip()
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}

    try:
        search_term = f"{q} board game"
        search_url = (
            f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch="
            f"{urllib.parse.quote(search_term)}&utf8=&format=json"
        )
        resp = requests.get(search_url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return None
        results = resp.json().get("query", {}).get("search", [])
        if not results:
            return None

        title = results[0].get("title")
        if not title:
            return None

        summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}"
        resp2 = requests.get(summary_url, headers=headers, timeout=timeout)
        if resp2.status_code != 200:
            return None

        img_url = resp2.json().get("thumbnail", {}).get("source")
        if not img_url:
            return None

        img_resp = requests.get(img_url, headers=headers, timeout=timeout + 5)
        if img_resp.status_code == 200 and len(img_resp.content) > 500:
            logger.info(f"Retrieved game image for '{q}' from Wikipedia")
            return img_resp.content
    except Exception as e:
        logger.debug(f"Wikipedia image search failed for '{q}': {e}")

    return None


def fetch_bing_game_image(game_name: str, timeout: int = 10) -> bytes | None:
    """Attempt to fetch board game cover from Bing Image search as fallback."""
    if not game_name or not game_name.strip():
        return None
    q = game_name.strip()
    search_term = f"{q} board game box"
    url = f"https://www.bing.com/images/search?q={urllib.parse.quote(search_term)}&form=HDRSC2"
    headers = {
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return None

        matches = re.findall(r'murl&quot;:&quot;(http[^&]+)&quot;', resp.text)
        if not matches:
            matches = re.findall(r'murl":"(http[^"]+)"', resp.text)
        if not matches:
            matches = re.findall(r'murl="(http[^"]+)"', resp.text)

        download_headers = {"User-Agent": DEFAULT_USER_AGENT}
        for raw_url in matches[:3]:
            img_url = html.unescape(raw_url)
            try:
                img_resp = requests.get(img_url, headers=download_headers, timeout=timeout + 5)
                if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                    logger.info(f"Retrieved game image for '{q}' from web search fallback")
                    return img_resp.content
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"Web image search failed for '{q}': {e}")

    return None


def fetch_fallback_game_image(game_name: str, timeout: int = 10) -> bytes | None:
    """Fallback search using Wikipedia then Bing images."""
    img = fetch_wikipedia_game_image(game_name, timeout=timeout)
    if img:
        return img
    img = fetch_bing_game_image(game_name, timeout=timeout)
    if img:
        return img
    return None


def fetch_bgg_game_image(game_name: str, timeout: int = 10, token: str | None = None) -> bytes | None:
    """
    Fetches the game image.
    If BGG_API_TOKEN is configured in environment (or provided), queries BoardGameGeek API first.
    If BGG_API_TOKEN is not configured or BGG returns no result / error,
    falls back to Wikipedia and web search.
    """
    if not game_name or not game_name.strip():
        return None

    q = game_name.strip()
    bgg_token = token if token is not None else getattr(config, "BGG_API_TOKEN", None)

    if bgg_token:
        img = fetch_bgg_api_image(q, token=bgg_token, timeout=timeout)
        if img:
            return img
        logger.info(f"BGG fetch for '{q}' failed or returned no image; falling back to web search")

    return fetch_fallback_game_image(q, timeout=timeout)

