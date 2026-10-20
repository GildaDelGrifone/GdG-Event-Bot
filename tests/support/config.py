from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from core import config
from tests.support.telegram import ADMIN_CHAT_ID


@contextmanager
def patched_config(**values):
    """Temporarily overrides core.config attributes, e.g. patched_config(ADMIN_CHAT_ID="999", DATA_DIR=tmp)."""
    with ExitStack() as stack:
        for name, value in values.items():
            if not hasattr(config, name):
                raise AttributeError(f"core.config has no setting {name}")
            stack.enter_context(patch.object(config, name, value))
        yield


def as_admin_chat(**extra):
    """patched_config with ADMIN_CHAT_ID matching tests.support.telegram.admin_update()."""
    return patched_config(ADMIN_CHAT_ID=ADMIN_CHAT_ID, **extra)


@contextmanager
def wordpress_credentials(url="https://example.com", username="testuser", password="testpass", category=None):
    with patched_config(WP_URL=url, WP_USERNAME=username, WP_APP_PASSWORD=password, WP_POST_CATEGORY=category):
        yield


@contextmanager
def eventbrite_credentials(**overrides):
    """Eventbrite fully configured (integration enabled); pass EVENTBRITE_* overrides, e.g. EVENTBRITE_LISTED=False."""
    values = {
        "EVENTBRITE_TOKEN": "eb-token",
        "EVENTBRITE_ORGANIZATION_ID": "org1",
        "EVENTBRITE_VENUE_ID": "venue1",
        "EVENTBRITE_ORGANIZER_ID": None,
        "EVENTBRITE_TIMEZONE": "Europe/Rome",
        "EVENTBRITE_CURRENCY": "EUR",
        "EVENTBRITE_LISTED": True,
        "EVENTBRITE_DEFAULT_START_TIME": "20:45",
        "EVENTBRITE_EVENT_DURATION_HOURS": 4.0,
        "EVENTBRITE_UNLIMITED_CAPACITY": 50,
        "EVENTBRITE_FULL_SYNC_MINUTES": 30,
        "EVENTBRITE_DELETE_CANCELLED": True,
        "EVENTBRITE_COLLECTION_ROLEPLAY": None,
        "EVENTBRITE_COLLECTION_BOARDGAMES": None,
        "EVENTBRITE_BOOKING_NOTIFICATIONS": True,
        **overrides,
    }
    with patched_config(**values):
        yield
