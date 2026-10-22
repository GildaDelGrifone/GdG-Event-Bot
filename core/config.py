import os

from dotenv import load_dotenv

# Load .env
if os.path.exists(".env"):
    load_dotenv(dotenv_path=".env")
else:
    load_dotenv()


def _env_bool(name, default):
    return os.getenv(name, "true" if default else "false").strip().lower() in ("true", "1", "yes")


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME")

PUBLIC_CHANNEL_ID = os.getenv("PUBLIC_CHANNEL_ID")
DISCUSSION_GROUP_ID = os.getenv("DISCUSSION_GROUP_ID")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
ALLOW_GROUP_EVENT_NEXT = _env_bool("ALLOW_GROUP_EVENT_NEXT", True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

BGG_API_TOKEN = os.getenv("BGG_API_TOKEN")

WP_URL = os.getenv("WP_URL")
WP_USERNAME = os.getenv("WP_USERNAME")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")
WP_POST_CATEGORY = os.getenv("WP_POST_CATEGORY")

IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")
IG_ACCOUNT_ID = os.getenv("IG_ACCOUNT_ID")

EVENTBRITE_TOKEN = os.getenv("EVENTBRITE_TOKEN")
EVENTBRITE_ORGANIZATION_ID = os.getenv("EVENTBRITE_ORGANIZATION_ID")
EVENTBRITE_VENUE_ID = os.getenv("EVENTBRITE_VENUE_ID")
EVENTBRITE_VENUE_ID_ALTERNATIVES = [v.strip() for v in os.getenv("EVENTBRITE_VENUE_ID_ALTERNATIVES", "").split(",") if v.strip()]
EVENTBRITE_ORGANIZER_ID = os.getenv("EVENTBRITE_ORGANIZER_ID")
EVENTBRITE_TIMEZONE = os.getenv("EVENTBRITE_TIMEZONE", "Europe/Rome")
EVENTBRITE_CURRENCY = os.getenv("EVENTBRITE_CURRENCY", "EUR")
EVENTBRITE_LISTED = _env_bool("EVENTBRITE_LISTED", True)
EVENTBRITE_DEFAULT_START_TIME = os.getenv("EVENTBRITE_DEFAULT_START_TIME", "20:45")
EVENTBRITE_EVENT_DURATION_HOURS = float(os.getenv("EVENTBRITE_EVENT_DURATION_HOURS", "4"))
EVENTBRITE_UNLIMITED_CAPACITY = int(os.getenv("EVENTBRITE_UNLIMITED_CAPACITY", "50"))
EVENTBRITE_POLL_MINUTES = int(os.getenv("EVENTBRITE_POLL_MINUTES", "2"))
EVENTBRITE_FULL_SYNC_MINUTES = int(os.getenv("EVENTBRITE_FULL_SYNC_MINUTES", "30"))
EVENTBRITE_DELETE_CANCELLED = _env_bool("EVENTBRITE_DELETE_CANCELLED", True)
EVENTBRITE_ONLY_MODE = _env_bool("EVENTBRITE_ONLY_MODE", False)
EVENTBRITE_COLLECTION_ROLEPLAY = os.getenv("EVENTBRITE_COLLECTION_ROLEPLAY") or None
EVENTBRITE_COLLECTION_BOARDGAMES = os.getenv("EVENTBRITE_COLLECTION_BOARDGAMES") or None
EVENTBRITE_BOOKING_NOTIFICATIONS = _env_bool("EVENTBRITE_BOOKING_NOTIFICATIONS", True)

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _env_log_level(name, default="INFO"):
    """A valid logging level name from the environment; a typo falls back to the default instead of stopping the bot."""
    value = os.getenv(name, default).strip().upper()
    return value if value in _LOG_LEVELS else default


LOG_LEVEL = _env_log_level("LOG_LEVEL")


def _env_time(name, default):
    """An (hour, minute) tuple from an HH:MM environment value; a typo falls back to the default instead of stopping the bot."""
    for value in (os.getenv(name, default), default):
        try:
            hour, minute = (int(part) for part in value.strip().split(":"))
        except ValueError:
            continue
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    raise ValueError(f"Invalid default time for {name}: {default}")


REPOSTS_TIME = _env_time("REPOSTS_TIME", "09:00")
RECAP_TIME = _env_time("RECAP_TIME", "16:00")
ARCHIVE_IMAGES_TIME = _env_time("ARCHIVE_IMAGES_TIME", "23:59")
ARCHIVE_LOGS_TIME = _env_time("ARCHIVE_LOGS_TIME", "00:05")
EVENTBRITE_CLEANUP_TIME = _env_time("EVENTBRITE_CLEANUP_TIME", "23:59")

MAX_EVENTS_PER_ROW = int(os.getenv("MAX_EVENTS_PER_ROW", "0"))

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
DEFAULT_DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DATA_DIR = os.getenv("DATA_DIR", DEFAULT_DATA_DIR)
FONTS_DIR = os.path.join(PROJECT_ROOT, "data")  # Fonts stay in the repo's data folder even with a custom DATA_DIR
DB_PATH = os.path.join(DATA_DIR, "bot_database.db")
LOGS_DIR = os.path.join(DATA_DIR, "logs")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
