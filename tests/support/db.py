import os
import tempfile
from unittest.mock import patch

import core.db as db
from core import config

SAMPLE_EVENT = {
    "title": "Avventura D&D",
    "date": "Venerdì 04-09-2026 21:00",
    "normalized_date": "04-09-2026",
    "system": "D&D 5e",
    "host": "Master DM",
    "seats": "4/4",
    "booked_seats": 0,
    "max_seats": 4,
    "description": "Una grande avventura",
}


class TempDBMixin:
    """Gives each test a fresh SQLite file (core.config.DB_PATH) plus self.temp_dir for other files.

    Mix in before the TestCase class: `class T(TempDBMixin, unittest.IsolatedAsyncioTestCase)`.
    """

    def setUp(self):
        super().setUp()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        db_patch = patch.object(config, "DB_PATH", self.test_db_path)
        db_patch.start()
        self.addCleanup(db_patch.stop)
        db.init_db()


def sample_event(**overrides):
    return {**SAMPLE_EVENT, **overrides}


def create_event(status="pending", original_text="raw text", image_path=None, message_link=None,
                 telegram_message_id=None, **overrides):
    """Inserts sample_event(**overrides) and returns its id; status other than 'pending' is applied afterwards."""
    event_id = db.insert_event(
        sample_event(**overrides), image_path, original_text,
        message_link=message_link, telegram_message_id=telegram_message_id,
    )
    if status != "pending":
        db.update_event_status(event_id, status)
    return event_id


# Shared fixtures from the old subscriber tests; the dicts are kept verbatim because tests assert on their fields.
SUBSCRIBED_EVENT = {
    "title": "Avventura D&D",
    "date": "Venerdì 21:00",
    "normalized_date": "2026-09-05",
    "system": "D&D 5e",
    "host": "Master John",
    "seats": "4/5",
    "booked_seats": 1,
    "max_seats": 5,
    "description": "Una grande avventura",
    "status": "approved",
}


def create_subscribed_event(**overrides):
    """An approved "Avventura D&D" (5 seats) with @mario (user 1001) booked on it; returns its id."""
    event_id = db.insert_event({**SUBSCRIBED_EVENT, **overrides}, None, "test original text")
    db.update_event_status(event_id, "approved")
    db.book_seat(event_id, 1001, "mario")
    return event_id


def create_deep_link_event():
    """An approved event whose title needs HTML escaping, used by the booking keyboard and deep-link tests."""
    event_id = db.insert_event({
        "title": "One-Shot D&D <Special>",
        "date": "Venerdì 20-09-2026",
        "system": "D&D 5e",
        "seats": 4,
        "max_seats": 4,
        "booked_seats": 0,
        "description": "Una fantastica avventura",
    }, None, "raw text")
    db.update_event_status(event_id, "approved")
    return event_id


def create_no_username_event():
    """An approved event used by the tests for subscribers without a Telegram username."""
    event_id = db.insert_event({
        "title": "One-Shot Senza Username",
        "date": "2026-10-10",
        "normalized_date": "2026-10-10",
        "system": "D&D 5e",
        "host": "Master",
        "seats": "3/3",
        "max_seats": 3,
        "booked_seats": 0,
        "image_path": "dummy.jpg",
        "message_link": "https://t.me/c/123/789",
    }, "dummy.jpg", "raw")
    db.update_event_status(event_id, "approved")
    return event_id


def create_unpublished_event():
    """An event still pending approval (not published in the channel)."""
    return db.insert_event({
        "title": "Unpublished Draft Event",
        "date": "Sabato 21:00",
        "normalized_date": "2026-10-10",
        "system": "Call of Cthulhu",
        "host": "Keeper",
        "seats": "4/4",
        "booked_seats": 0,
        "max_seats": 4,
        "description": "Una sessione non ancora pubblicata",
    }, None, "raw text")
