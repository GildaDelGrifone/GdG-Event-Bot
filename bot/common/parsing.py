import re

from core.db import get_event_by_telegram_message_id, get_event_by_admin_message_id

UNLIMITED_SEATS_DISPLAY = "no limit"
UNLIMITED_SEAT_TOKENS = {"null", "nessuno", "illimitati", "unlimited", "none", "0", ""}

EVENT_KEYWORD_PATTERNS = [
    re.compile(r"\b(titolo|posti(\s+liberi)?|descrizione|sinossi|gioco|quando|data)\s*:", re.IGNORECASE),
    re.compile(r"\b(gioco\s+da\s+tavolo|gioco\s+di\s+ruolo|oneshot|one[\s\-]shot)\b", re.IGNORECASE),
]

EVENT_CALLBACK_PREFIXES = (
    "publish_event_",
    "discard_event_",
    "cancel_event_",
    "reactivate_event_",
    "manage_subs_",
    "sub_inc_",
    "sub_dec_",
    "sub_addnew_",
    "close_subs_",
    "book_",
    "unbook_",
    "show_subs_",
)


def contains_event_keywords(text: str) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in EVENT_KEYWORD_PATTERNS)


def parse_seats_input(value):
    """Returns None for unlimited seats, otherwise (free, total); free is None when only a total was given.

    Raises ValueError for malformed input.
    """
    clean = str(value).strip().lower()
    if clean in UNLIMITED_SEAT_TOKENS:
        return None
    if "/" in clean:
        parts = clean.split("/")
        return int(parts[0].strip()), int(parts[1].strip())
    return None, int(clean)


def extract_event_id_from_reply(reply_msg):
    if not reply_msg:
        return None

    if reply_msg.reply_markup and reply_msg.reply_markup.inline_keyboard:
        for row in reply_msg.reply_markup.inline_keyboard:
            for btn in row:
                cb_data = getattr(btn, "callback_data", None)
                if not (cb_data and isinstance(cb_data, str)):
                    continue
                for prefix in EVENT_CALLBACK_PREFIXES:
                    if cb_data.startswith(prefix):
                        try:
                            return int(cb_data[len(prefix):].split("_")[0])
                        except (IndexError, ValueError):
                            pass

    raw_content = getattr(reply_msg, "caption", None) or getattr(reply_msg, "text", None) or ""
    if isinstance(raw_content, str):
        m = re.search(r"(?:evento\s*)?#(\d+)", raw_content, re.IGNORECASE)
        if m:
            return int(m.group(1))

    msg_id = getattr(reply_msg, "message_id", None)
    if isinstance(msg_id, int):
        ev = get_event_by_telegram_message_id(msg_id) or get_event_by_admin_message_id(msg_id)
        if ev:
            return ev['id']
    return None
