import json
import logging
import re

import google.generativeai as genai

from core import config

logger = logging.getLogger(__name__)

GEMINI_DEPLETED_ALERT = "🚨 Errore Gemini AI (Crediti esauriti):\n429 Your prepayment credits are depleted."
TRUTHY_TOKENS = {"true", "1", "yes", "si", "sì"}

# "Posti: X/Y" always means X free seats out of Y at the table; the bot only manages the X free ones
_SEATS_FRACTION_RE = re.compile(r'Posti(?:\s+liberi|\s+disponibili)?\s*:\s*(\d+)\s*/\s*(\d+)', re.IGNORECASE)
_SEATS_SINGLE_RE = re.compile(r'Posti(?:\s+liberi|\s+disponibili)?\s*:\s*(\d+)(?!\s*/)', re.IGNORECASE)

genai.configure(api_key=config.GEMINI_API_KEY)


class GeminiQuotaError(Exception):
    """Raised when Gemini API quota is exceeded or prepayment credits are depleted."""


def strip_json_fence(text):
    text = text.strip()
    if text.startswith("```json"):
        return text[7:-3].strip()
    if text.startswith("```"):
        return text[3:-3].strip()
    return text


def is_quota_error(err):
    err_str = str(err).lower()
    return "429" in err_str or "prepayment credits are depleted" in err_str or "quota" in err_str or "resourceexhausted" in err_str


def coerce_bool(value):
    return value.strip().lower() in TRUTHY_TOKENS if isinstance(value, str) else bool(value)


def generate_text(prompt):
    """Runs prompt on config.GEMINI_MODEL; quota/credit failures surface as GeminiQuotaError."""
    try:
        return genai.GenerativeModel(config.GEMINI_MODEL).generate_content(prompt).text
    except Exception as e:
        if is_quota_error(e):
            raise GeminiQuotaError(str(e)) from e
        raise


def _event_prompt(message_text):
    return f"""
    You are an AI parser for a tabletop games association in Italy (Gilda del Grifone).
    Analyze the following message and extract the event information into a strict JSON format.
    The message usually announces a game session (roleplaying, board game, etc.).

    If the message is NOT an event announcement (e.g. general chat, irrelevant to games),
    return EXACTLY: {{"is_event": false}}

    If it is an event, extract the following fields:
    - "title": The title of the event or game.
    - "date": The date and time (keep the string exactly as in the message or format nicely).
    - "normalized_date": The date converted to DD-MM-YYYY format (assuming the current year is 2026 if not specified).
    - "system": The game system or genre (if any, e.g., "Sine Requie", "D&D", or board game name).
    - "host": The Master, Host, or Organizer's name and/or tag.
    - "seats": The display string for available seats (e.g. "2/4", "no limit"). If 0 seats are free, output "0/0 Completo".
    - "booked_seats": The number of already booked seats (integer, default 0).
      CRITICAL RULE FOR SEATS:
      In this Italian association, "Posti: X/Y", "Posti liberi: X/Y", or "Posti disponibili: X/Y" ALWAYS means:
      X = FREE/AVAILABLE seats that can be booked through this bot.
      Y = TOTAL seats at the table. Any difference (Y - X) represents players already booked outside the bot (e.g. host's friends).
      IMPORTANT: The bot ONLY manages bookings for the open seats.
      Therefore, the event's bookable capacity MUST always be X:
      max_seats = X
      booked_seats = 0
      seats = "X/X" (or "0/0 Completo" if X is 0)

      Examples:
      - "Posti: 2/2" -> 2 free seats -> booked_seats = 0, max_seats = 2, seats = "2/2"
      - "Posti: 1/4" -> 1 free seat -> booked_seats = 0, max_seats = 1, seats = "1/1"
      - "Posti: 4/5" -> 4 free seats -> booked_seats = 0, max_seats = 4, seats = "4/4"
      - "Posti liberi: 2/4" -> 2 free seats -> booked_seats = 0, max_seats = 2, seats = "2/2"
      - "Posti: 0/3 Completo" -> 0 free seats -> booked_seats = 0, max_seats = 0, seats = "0/0 Completo"
      - "Posti: 4" (single number, no slash) -> 4 total available seats -> booked_seats = 0, max_seats = 4, seats = "4/4"
      - "Posti: no limit" or "quanti volete" -> booked_seats = 0, max_seats = null, seats = "no limit"
    - "max_seats": The maximum number of available seats (integer, or null if there is no limit).
    - "extra_info": Additional metadata or disclaimers if present in the message, specifically:
      - Difficulty / Beginner friendliness (e.g. "Difficoltà: adatto a tutti", "Adatto a neofiti: Sì")
      - Format / Duration / Campaign info (e.g. "ONESHOT", "CAMPAGNA (5 episodi)", "Durata: 3 ore")
      - Content warnings, safety tools, disclaimers (e.g. "Attenzione: gore, violenza", "X-Card: droghe", "Avviso: Effetti audio")
      - Genre / Themes (e.g. "Genere: Horror / Investigativo")
      Format them cleanly as short bulleted lines (using "• ") or concise text. If none of these exist in the message, output "".
    - "description": The synopsis or pitch of the event (focus on the story or game description; do not duplicate lines already extracted into extra_info).
    - "is_roleplay": Boolean (true or false). Output true if the event is a tabletop roleplaying game session (RPG / GDR, e.g., D&D, Pathfinder, Call of Cthulhu, Sine Requie, Cyberpunk, etc.) where someone acts as Master / Game Master / Dungeon Master. Output false if it is a board game, card game, tournament, or other non-RPG event (where the organizer is a Host).

    Return ONLY valid JSON.

    Message:
    {message_text}
    """


def _apply_seat_safety_net(data, message_text):
    """Overrides the AI's seat fields with what the "Posti: X[/Y]" line actually says."""
    m = _SEATS_FRACTION_RE.search(message_text) or _SEATS_SINGLE_RE.search(message_text)
    if not m:
        return
    free = int(m.group(1))
    data['max_seats'] = free
    data['booked_seats'] = 0
    data['seats'] = "0/0 Completo" if free == 0 else f"{free}/{free}"


def parse_event_message(message_text):
    try:
        logger.info("AI Parser: Sending message to Gemini for event extraction...")
        data = json.loads(strip_json_fence(generate_text(_event_prompt(message_text))))

        if isinstance(data, dict) and data.get("is_event", True):
            data['extra_info'] = str(data.get('extra_info') or '').strip()
            data['is_roleplay'] = coerce_bool(data.get('is_roleplay'))
            _apply_seat_safety_net(data, message_text)
            logger.info(f"AI Parser: Successfully parsed event '{data.get('title')}' for date '{data.get('date')}'.")
        elif isinstance(data, dict):
            logger.info("AI Parser: Message identified as non-event (is_event=False).")
        return data
    except GeminiQuotaError as e:
        logger.error(f"Error parsing message with AI: {e}")
        raise
    except Exception as e:
        logger.error(f"Error parsing message with AI: {e}")
        return None


def _article_prompt(recap_text, event_list):
    events_details = ""
    for ev in event_list:
        link = ev.get('message_link') or 'Link non disponibile'
        img_url = ev.get('wp_media_url')
        img_info = f" | Image URL: {img_url}" if img_url else ""
        events_details += f"- {ev.get('title')}: {link}{img_info}\n"

    return f"""
    You are an AI generating an engaging article for a tabletop games association's WordPress blog.
    Write an article in Italian summarizing the events for the upcoming game nights based on the recap text.
    Make it enthusiastic and welcoming.

    CRITICAL INSTRUCTIONS:
    - You must include the direct Telegram event link for each event in the article text, using the provided list below. Do not use placeholders like [Inserisci qui i link diretti agli eventi].
    - If you cite Destard or ManueleAbi, specify clearly that they are Telegram usernames. For example, use "l'utente Telegram @Destard (https://t.me/Destard)" and "l'utente Telegram @ManueleAbi (https://t.me/ManueleAbi)".
    - If an "Image URL" is provided for an event in the list below, you MUST embed it in the article body exactly where that event is described using an HTML <img> tag with a maximum size constraint (e.g., <img src="..." alt="..." style="max-width:400px; max-height:400px; width:auto; height:auto; margin-bottom:15px;">). Do not mention or include HTML tags for the daily collage, as the system will automatically attach it as the article's featured image (Immagine in evidenza).

    Recap Info:
    {recap_text}

    Event Links to include:
    {events_details}

    Return the response as HTML (just the content to put in the post body, no <html> or <body> tags).
    """


def generate_wordpress_article(recap_text, event_list):
    try:
        logger.info("AI Parser: Requesting WordPress article generation from Gemini...")
        article = generate_text(_article_prompt(recap_text, event_list)).strip()
        logger.info("AI Parser: Successfully generated WordPress article content.")
        return article
    except GeminiQuotaError as e:
        logger.error(f"Error generating WP article with AI: {e}")
        raise
    except Exception as e:
        logger.error(f"Error generating WP article with AI: {e}")
        return None
