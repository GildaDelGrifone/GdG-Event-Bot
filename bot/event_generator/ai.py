import json
import logging
import re
from datetime import datetime

from core.ai_parser import GeminiQuotaError, apply_seat_safety_net, coerce_bool, generate_text, strip_json_fence
from utils.date_utils import DAYS_IT
from utils.templates.common import CAPTION_LIMIT

logger = logging.getLogger(__name__)

# Informal "6 posti" / "3 posti liberi" (the "Posti: X[/Y]" form is handled by apply_seat_safety_net)
_SEATS_COUNT_RE = re.compile(r'\b(\d+)\s+posti\b', re.IGNORECASE)


def _build_prompt(prompt_text, now):
    today_context = f"{DAYS_IT[now.weekday()]} {now.strftime('%d-%m-%Y')} (Year: 2026)"
    return f"""
You are an AI assistant for a tabletop games association.
The user provides informal instructions to create a new gaming event (e.g., game title(s), date, host, seats, etc.).
Analyze the user's message and generate a structured JSON object.

Context:
- Current date reference: {today_context}.
- Standard default start time: 21:00 (if no time specified).

Required JSON structure:
{{
  "title": "Title of the event or game(s). E.g. 'Catan', 'Catan & Carcassonne', or 'D&D 5e: Il Tesoro della Regina'",
  "games": ["List of individual game titles to search on BoardGameGeek for box art, e.g. ['Catan'] or ['Catan', 'Carcassonne']"],
  "bgg_ids": {{"<each title exactly as in games>": "its BoardGameGeek numeric ID (e.g. 13 for Catan) or null"}},
  "date": "Italian date string, e.g. 'Venerdì 10-10-2026 21:00' or 'Domenica 04 Ottobre 2026 21:00'",
  "normalized_date": "Strict DD-MM-YYYY format, e.g. '10-10-2026'",
  "system": "Game system or category, e.g. 'Board Game', 'Giochi da Tavolo', 'D&D 5e', 'Call of Cthulhu'",
  "host": "Master or Host name/handle (e.g. '@Destard' or 'Destard'). If unknown, 'N/A'",
  "seats": "Display string for seats: 'N/N' where N is max_seats, or 'no limit' (see the SEATS rule)",
  "booked_seats": 0,
  "max_seats": "Integer number of bookable seats, or null for no limit (see the SEATS rule)",
  "extra_info": "Additional metadata (difficulty, beginner friendly, duration, tags) if mentioned, or empty string",
  "is_roleplay": false,
  "description": "Engaging, captivating synopsis/pitch for the game(s) in Italian (theme, objective, vibe)."
}}

CRITICAL RULES:
1. "description" MUST BE CONCISE: maximum 350-400 characters!
   The entire Telegram post (including title, host, date, seats, and description) MUST fit within Telegram's strict {CAPTION_LIMIT}-character caption limit.
2. "games" must contain only clean game names without dates, hosts, or extra words (e.g. ["Root", "Wingspan"]).
3. "bgg_ids" are checked against BoardGameGeek before use: give an ID only if you know it, null is better than a guess.
4. SEATS: a seat count stated in the user's instructions ALWAYS wins. It overrides BoardGameGeek data,
   the game's box and its official player count. Examples: "6 posti", "posti: 3", "Posti liberi: 2/4",
   "per 5 persone", "4 giocatori", "posti illimitati" / "senza limite".
   - "X/Y" means X free seats out of Y at the table: max_seats = X, seats = "X/X".
   - Unlimited: max_seats = null, seats = "no limit".
   - ONLY if the instructions give no seat number at all, use the game's maximum player count
     (with several games, the largest one). If that is unknown too (e.g. a roleplaying session), use null / "no limit".
   - booked_seats is always 0.
5. Return ONLY valid JSON, with no markdown outside ```json blocks.

User Instructions:
{prompt_text}
"""


def _apply_seats(data, prompt_text):
    """Seats stated in the instructions beat Gemini's answer (which may come from the game's player count)."""
    if not apply_seat_safety_net(data, prompt_text):
        m = _SEATS_COUNT_RE.search(prompt_text)
        if m:
            data["max_seats"] = int(m.group(1))
    try:
        max_seats = int(data.get("max_seats"))
    except (TypeError, ValueError):
        max_seats = None
    if max_seats is not None and max_seats < 0:
        max_seats = None
    data["max_seats"] = max_seats
    data["booked_seats"] = 0
    if max_seats is None:
        data["seats"] = "no limit"
    else:
        data["seats"] = "0/0 Completo" if max_seats == 0 else f"{max_seats}/{max_seats}"


def normalize_generated_event(data, prompt_text=""):
    data["extra_info"] = str(data.get("extra_info") or "").strip()
    data["description"] = str(data.get("description") or "").strip()
    _apply_seats(data, prompt_text or "")

    data["is_roleplay"] = coerce_bool(data.get("is_roleplay"))

    games = data.get("games")
    if not isinstance(games, list):
        if isinstance(games, str) and games.strip():
            data["games"] = [games.strip()]
        elif data.get("title"):
            data["games"] = [data["title"]]
        else:
            data["games"] = []
    data["bgg_ids"] = normalize_bgg_ids(data.get("bgg_ids"))
    return data


def normalize_bgg_ids(value):
    """{game: positive int}; anything else is dropped."""
    if not isinstance(value, dict):
        return {}
    ids = {}
    for game, bgg_id in value.items():
        try:
            bgg_id = int(bgg_id)
        except (TypeError, ValueError):
            continue
        if bgg_id > 0:
            ids[str(game)] = bgg_id
    return ids


def generate_event_data_with_ai(prompt_text: str) -> dict | None:
    """Asks Gemini for standardized event fields plus the list of games to look up on BoardGameGeek."""
    try:
        logger.info("Event Generator: Sending prompt to Gemini for event generation...")
        data = json.loads(strip_json_fence(generate_text(_build_prompt(prompt_text, datetime.now()))))
        return normalize_generated_event(data, prompt_text) if isinstance(data, dict) else None
    except GeminiQuotaError as e:
        logger.error(f"Error generating event with Gemini: {e}")
        raise
    except Exception as e:
        logger.error(f"Error generating event with Gemini: {e}")
        return None
