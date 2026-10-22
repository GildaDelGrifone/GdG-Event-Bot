import html
import io
import json
import logging
import re
import urllib.parse

import requests
from PIL import Image

from core import config
from core.ai_parser import generate_from_image

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "GdG-Event-Bot/1.0 (+https://github.com/destard/GdG-Event-Bot)"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
BGG_SEARCH_URL = "https://api.geekdo.com/api/geekitems?objecttype=thing&search="
BGG_DETAIL_URL = "https://api.geekdo.com/api/geekitems?objecttype=thing&objectid="
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
COMMONS_FILE_URL = "https://commons.wikimedia.org/wiki/Special:FilePath/"
# Wikimedia throttles anonymous clients; a descriptive User-Agent with a contact URL is required
WIKIMEDIA_HEADERS = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}
MIN_IMAGE_BYTES = 1000
BING_MAX_CANDIDATES = 3
BING_META_RE = re.compile(r'\sm="(\{[^"]+\})"')
GAME_SITE_RE = re.compile(r"boardgamegeek|geekdo|dungeondice|amazon|games", re.I)
GAME_DESCRIPTION_RE = re.compile(
    r"\b(board|card|tabletop|dice|party|strategy|miniatures?)[ -]?games?\b|\bgioc\w* (da tavolo|di carte)\b",
    re.I,
)
STOPWORDS = {"the", "of", "and", "a", "an", "il", "la", "lo", "le", "gli", "di", "del", "della", "e", "de"}
BGG_GAME_SUBTYPES = {"boardgame", "boardgameexpansion"}
BGG_HEADERS = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}
GEMINI_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
VERIFY_IMAGE_PROMPT = (
    "Is this image the box cover, cover art or components of the tabletop game '{game}'? Answer only YES or NO."
)

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

        item = bgg_item_by_id(object_id, timeout, headers=headers)
        if item is None:
            return None

        image_url = bgg_image_url(item)
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


def bgg_item_by_id(object_id, timeout: int = 10, headers: dict = BGG_HEADERS) -> dict | None:
    """BGG item detail; unlike search, it answers without a token."""
    try:
        resp = requests.get(f"{BGG_DETAIL_URL}{object_id}", headers=headers, timeout=timeout)
        if resp.status_code != 200:
            logger.warning(f"BGG item detail fetch for ID {object_id} returned {resp.status_code}")
            return None
        return resp.json().get("item") or None
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"BGG item detail fetch for ID {object_id} failed: {e}")
        return None


def _normalize_name(name: str) -> str:
    return " ".join(re.findall(r"\w+", name.lower()))


def bgg_item_matches(item: dict, game_name: str) -> bool:
    """The item is a board game named game_name, in any language, optionally followed by a ': subtitle'."""
    if item.get("subtype") not in BGG_GAME_SUBTYPES:
        return False
    wanted = _normalize_name(game_name)
    names = [item.get("name") or ""] + [alt.get("name") or "" for alt in item.get("alternatenames") or []]
    return any(wanted in (_normalize_name(name), _normalize_name(re.split(r"[:–—]|\s-\s", name)[0]))
               for name in names if name)


def fetch_bgg_image_by_id(object_id, game_name: str, timeout: int = 10) -> bytes | None:
    """BGG box art for a known ID, used only if BGG's own names for that ID match game_name."""
    item = bgg_item_by_id(object_id, timeout)
    if item is None:
        return None
    if not bgg_item_matches(item, game_name):
        logger.info(f"BGG ID {object_id} is '{item.get('name')}', not '{game_name}'; ignored")
        return None
    image_url = bgg_image_url(item)
    img = _download_image(image_url, {"User-Agent": DEFAULT_USER_AGENT}, timeout) if image_url else None
    if img:
        logger.info(f"Retrieved game image for '{game_name}' from BoardGameGeek ID {object_id}")
    return img


def _download_image(url: str, headers: dict, timeout: int) -> bytes | None:
    try:
        resp = requests.get(url, headers=headers, timeout=timeout + 5)
    except requests.RequestException as e:
        logger.debug(f"Image download failed for {url}: {e}")
        return None
    if resp.status_code == 200 and len(resp.content) > MIN_IMAGE_BYTES:
        return resp.content
    return None


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def mentions_game(text: str, game_name: str) -> bool:
    """True when text contains at least half of game_name's significant words (all its words if none are)."""
    query_words = _words(game_name)
    wanted = {w for w in query_words if w not in STOPWORDS and (len(w) > 2 or w.isdigit())} or query_words
    return bool(wanted) and 2 * len(wanted & _words(text)) >= len(wanted)


def _wikipedia_summary(lang: str, title: str, timeout: int) -> dict | None:
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title.replace(' ', '_'), safe='')}"
    resp = requests.get(url, headers=WIKIMEDIA_HEADERS, timeout=timeout)
    return resp.json() if resp.status_code == 200 else None


def _summary_image_url(summary: dict) -> str | None:
    """Prefers the full-size 'originalimage' over the 'thumbnail'."""
    return (summary.get("originalimage") or {}).get("source") or (summary.get("thumbnail") or {}).get("source")


def wikidata_entity_names(entity):
    """Labels, aliases and Wikipedia titles without their '(board game)'-style qualifier."""
    names = [label.get("value", "") for label in entity.get("labels", {}).values()]
    names += [alias.get("value", "") for aliases in entity.get("aliases", {}).values() for alias in aliases]
    names += [re.sub(r"\s*\(.*\)$", "", link.get("title", "")) for link in entity.get("sitelinks", {}).values()]
    return [name.lower() for name in names if name]


def rank_wikidata_entities(entities, query):
    """Exact (case-insensitive) name matches first, then the other hits in search order."""
    q_norm = query.lower()
    exact = [entity for entity in entities if q_norm in wikidata_entity_names(entity)]
    return exact + [entity for entity in entities if entity not in exact]


def wikidata_bgg_ids(entity: dict) -> list[str]:
    """BoardGameGeek IDs (P2339) of a Wikidata item."""
    claims = entity.get("claims", {}).get("P2339", [])
    return [v for v in (c.get("mainsnak", {}).get("datavalue", {}).get("value") for c in claims) if v]


def wikidata_image_url(entity: dict, timeout: int) -> str | None:
    """Lead image of the en/it Wikipedia article (usually the box art), else the Commons image (P18)."""
    sitelinks = entity.get("sitelinks", {})
    for lang in ("en", "it"):
        title = sitelinks.get(f"{lang}wiki", {}).get("title")
        summary = _wikipedia_summary(lang, title, timeout) if title else None
        url = _summary_image_url(summary) if summary else None
        if url:
            return url
    for claim in entity.get("claims", {}).get("P18", []):
        file_name = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if file_name:
            return f"{COMMONS_FILE_URL}{urllib.parse.quote(file_name.replace(' ', '_'))}?width=1000"
    return None


def fetch_wikidata_game_image(game_name: str, timeout: int = 10) -> bytes | None:
    """Looks the game up among Wikidata items that have a BoardGameGeek ID (P2339), so homonyms are skipped.
    The BGG box art for that ID comes first, the en/it Wikipedia or Commons image second."""
    if not game_name or not game_name.strip():
        return None
    q = game_name.strip()

    try:
        resp = requests.get(WIKIDATA_API_URL, headers=WIKIMEDIA_HEADERS, timeout=timeout, params={
            "action": "query", "list": "search", "srsearch": f"{q} haswbstatement:P2339", "srlimit": 5, "format": "json",
        })
        if resp.status_code != 200:
            return None
        ids = [hit["title"] for hit in resp.json().get("query", {}).get("search", []) if hit.get("title")]
        if not ids:
            logger.info(f"No Wikidata board game found for '{q}'")
            return None

        resp = requests.get(WIKIDATA_API_URL, headers=WIKIMEDIA_HEADERS, timeout=timeout, params={
            "action": "wbgetentities", "ids": "|".join(ids), "props": "labels|aliases|sitelinks|claims",
            "languages": "en|it", "sitefilter": "enwiki|itwiki", "format": "json",
        })
        if resp.status_code != 200:
            return None
        entities = resp.json().get("entities", {})

        for entity in rank_wikidata_entities([entities[i] for i in ids if i in entities], q):
            for bgg_id in wikidata_bgg_ids(entity):
                img = fetch_bgg_image_by_id(bgg_id, q, timeout)
                if img:
                    return img
            img_url = wikidata_image_url(entity, timeout)
            img = _download_image(img_url, WIKIMEDIA_HEADERS, timeout) if img_url else None
            if img:
                logger.info(f"Retrieved game image for '{q}' from Wikidata {entity.get('id')}")
                return img
        return None
    except Exception as e:
        logger.debug(f"Wikidata image search failed for '{q}': {e}")
        return None


def fetch_wikipedia_game_image(game_name: str, timeout: int = 10) -> bytes | None:
    """Lead image of the first Wikipedia hit that is named after the game and described as a game."""
    if not game_name or not game_name.strip():
        return None
    q = game_name.strip()

    try:
        resp = requests.get(WIKIPEDIA_SEARCH_URL, headers=WIKIMEDIA_HEADERS, timeout=timeout, params={
            "action": "query", "list": "search", "srsearch": f"{q} board game", "srlimit": 3, "format": "json",
        })
        if resp.status_code != 200:
            return None

        for hit in resp.json().get("query", {}).get("search", []):
            title = hit.get("title")
            if not title or not mentions_game(title, q):
                continue
            summary = _wikipedia_summary("en", title, timeout)
            if not summary:
                continue
            about = f"{summary.get('description', '')} {summary.get('extract', '')}"
            if not GAME_DESCRIPTION_RE.search(about):
                logger.debug(f"Wikipedia page '{title}' is not about a game; skipped")
                continue
            img_url = _summary_image_url(summary)
            img = _download_image(img_url, WIKIMEDIA_HEADERS, timeout) if img_url else None
            if img:
                logger.info(f"Retrieved game image for '{q}' from Wikipedia page '{title}'")
                return img
    except Exception as e:
        logger.debug(f"Wikipedia image search failed for '{q}': {e}")

    return None


def bing_candidates(page_html: str) -> list[dict]:
    """Image results as {url, title, page}; the bare 'murl' scrape (no title/page) is the fallback."""
    candidates = []
    for raw in BING_META_RE.findall(page_html):
        try:
            meta = json.loads(html.unescape(raw))
        except ValueError:
            continue
        if meta.get("murl"):
            candidates.append({"url": meta["murl"], "title": meta.get("t", ""), "page": meta.get("purl", "")})
    if candidates:
        return candidates

    matches = re.findall(r'murl&quot;:&quot;(http[^&]+)&quot;', page_html)
    if not matches:
        matches = re.findall(r'murl":"(http[^"]+)"', page_html)
    if not matches:
        matches = re.findall(r'murl="(http[^"]+)"', page_html)
    return [{"url": html.unescape(m), "title": "", "page": ""} for m in matches]


def image_matches_game(image_bytes: bytes, game_name: str) -> bool:
    """Asks Gemini whether the image shows the game; any doubt or error (quota included) counts as no."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            mime_type = Image.MIME.get(img.format)
    except Exception:
        return False
    if mime_type not in GEMINI_IMAGE_TYPES:
        return False

    try:
        answer = generate_from_image(VERIFY_IMAGE_PROMPT.format(game=game_name), image_bytes, mime_type)
    except Exception as e:
        logger.warning(f"Gemini could not verify the image for '{game_name}': {e}")
        return False
    return (answer or "").strip().upper().startswith("YES")


def fetch_bing_game_image(game_name: str, timeout: int = 10) -> bytes | None:
    """Bing Images as last resort: results must mention the game and every image is confirmed by Gemini."""
    if not game_name or not game_name.strip():
        return None
    q = game_name.strip()
    if not getattr(config, "GEMINI_API_KEY", None):
        logger.info(f"Skipping web image search for '{q}': GEMINI_API_KEY is needed to verify the results")
        return None

    search_term = f'"{q}" board game'
    url = f"https://www.bing.com/images/search?q={urllib.parse.quote(search_term)}&form=HDRSC2"
    headers = {
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return None

        candidates = [c for c in bing_candidates(resp.text)
                      if mentions_game(f"{c['title']} {c['page']} {c['url']}", q)]
        # Board game sites and shops first; sorted() keeps Bing's order otherwise
        candidates.sort(key=lambda c: not GAME_SITE_RE.search(urllib.parse.urlparse(c["page"] or c["url"]).netloc))

        download_headers = {"User-Agent": DEFAULT_USER_AGENT}
        for candidate in candidates[:BING_MAX_CANDIDATES]:
            img = _download_image(candidate["url"], download_headers, timeout)
            if img and image_matches_game(img, q):
                logger.info(f"Retrieved game image for '{q}' from web search ({candidate['url']})")
                return img
            logger.info(f"Web search image rejected for '{q}': {candidate['url']}")
    except Exception as e:
        logger.debug(f"Web image search failed for '{q}': {e}")

    return None


def fetch_fallback_game_image(game_name: str, timeout: int = 10) -> bytes | None:
    """Wikidata, then a validated Wikipedia search, then Gemini-verified Bing images."""
    for fetch in (fetch_wikidata_game_image, fetch_wikipedia_game_image, fetch_bing_game_image):
        img = fetch(game_name, timeout=timeout)
        if img:
            return img
    return None


def fetch_bgg_game_image(game_name: str, timeout: int = 10, token: str | None = None,
                         bgg_id: int | None = None) -> bytes | None:
    """
    Fetches the game image.
    If BGG_API_TOKEN is configured in environment (or provided), queries BoardGameGeek API first.
    Then bgg_id (the AI's guess, checked against BGG's names) is tried,
    then Wikidata/Wikipedia and the Gemini-verified web search.
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

    if isinstance(bgg_id, int) and not isinstance(bgg_id, bool) and bgg_id > 0:
        img = fetch_bgg_image_by_id(bgg_id, q, timeout)
        if img:
            return img

    return fetch_fallback_game_image(q, timeout=timeout)

