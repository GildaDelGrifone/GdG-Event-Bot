import json
import logging
from datetime import datetime

from core.ai_parser import GeminiQuotaError, coerce_bool, generate_text, strip_json_fence
from utils.date_utils import DAYS_IT

logger = logging.getLogger(__name__)


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
  "date": "Italian date string, e.g. 'Venerdì 10-10-2026 21:00' or 'Domenica 04 Ottobre 2026 21:00'",
  "normalized_date": "Strict DD-MM-YYYY format, e.g. '10-10-2026'",
  "system": "Game system or category, e.g. 'Board Game', 'Giochi da Tavolo', 'D&D 5e', 'Call of Cthulhu'",
  "host": "Master or Host name/handle (e.g. '@Destard' or 'Destard'). If unknown, 'N/A'",
  "seats": "Display string for seats, e.g. '4/4', '6/6', or 'no limit'",
  "booked_seats": 0,
  "max_seats": 4,
  "extra_info": "Additional metadata (difficulty, beginner friendly, duration, tags) if mentioned, or empty string",
  "is_roleplay": false,
  "description": "Engaging, captivating synopsis/pitch for the game(s) in Italian (theme, objective, vibe)."
}}

CRITICAL RULES:
1. "description" MUST BE CONCISE: maximum 350-400 characters!
   The entire Telegram post (including title, host, date, seats, and description) MUST fit within Telegram's strict 1024-character caption limit.
2. "games" must contain only clean game names without dates, hosts, or extra words (e.g. ["Root", "Wingspan"]).
3. Return ONLY valid JSON, with no markdown outside ```json blocks.

User Instructions:
{prompt_text}
"""


def normalize_generated_event(data):
    data["extra_info"] = str(data.get("extra_info") or "").strip()
    data["description"] = str(data.get("description") or "").strip()
    data["booked_seats"] = 0

    data["is_roleplay"] = coerce_bool(data.get("is_roleplay"))

    games = data.get("games")
    if not isinstance(games, list):
        if isinstance(games, str) and games.strip():
            data["games"] = [games.strip()]
        elif data.get("title"):
            data["games"] = [data["title"]]
        else:
            data["games"] = []
    return data


def generate_event_data_with_ai(prompt_text: str) -> dict | None:
    """Asks Gemini for standardized event fields plus the list of games to look up on BoardGameGeek."""
    try:
        logger.info("Event Generator: Sending prompt to Gemini for event generation...")
        data = json.loads(strip_json_fence(generate_text(_build_prompt(prompt_text, datetime.now()))))
        return normalize_generated_event(data) if isinstance(data, dict) else None
    except GeminiQuotaError as e:
        logger.error(f"Error generating event with Gemini: {e}")
        raise
    except Exception as e:
        logger.error(f"Error generating event with Gemini: {e}")
        return None
