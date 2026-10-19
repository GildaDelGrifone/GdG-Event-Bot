import os
import sqlite3
import tempfile
import unittest

import core.db as db
from tests.support.config import patched_config


class TestSchemaMigrations(unittest.TestCase):
    def test_init_db_migrates_is_roleplay_column(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        legacy_db_path = os.path.join(temp_dir.name, "legacy_events.db")
        with sqlite3.connect(legacy_db_path) as conn:
            conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, date TEXT)")
            conn.commit()

        with patched_config(DB_PATH=legacy_db_path):
            db.init_db()
        with sqlite3.connect(legacy_db_path) as conn:
            cols = [c[1] for c in conn.execute("PRAGMA table_info(events)").fetchall()]
            self.assertIn("is_roleplay", cols)


class TestEventbriteSchema(unittest.TestCase):
    def test_init_db_migrates_eventbrite_columns_and_index(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        legacy_db_path = os.path.join(temp_dir.name, "legacy.db")
        with sqlite3.connect(legacy_db_path) as conn:
            conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT)")
            conn.execute("CREATE TABLE reservations (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER)")

        with patched_config(DB_PATH=legacy_db_path):
            db.init_db()
            db.init_db()  # idempotent
        with sqlite3.connect(legacy_db_path) as conn:
            event_cols = {c[1] for c in conn.execute("PRAGMA table_info(events)")}
            res_cols = {c[1] for c in conn.execute("PRAGMA table_info(reservations)")}
            indexes = {r[1] for r in conn.execute("PRAGMA index_list(reservations)")}
        self.assertTrue({
            "eventbrite_event_id", "eventbrite_url", "eventbrite_ticket_class_id", "eventbrite_status",
            "eventbrite_quantity_total", "eventbrite_content_version", "eventbrite_synced_at",
        } <= event_cols)
        self.assertTrue({"source", "eventbrite_order_id"} <= res_cols)
        self.assertIn("idx_res_eb_order", indexes)

    def test_new_database_has_eventbrite_defaults(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        with patched_config(DB_PATH=os.path.join(temp_dir.name, "new.db")):
            db.init_db()
            event_id = db.insert_event({"title": "T"}, None, "raw")
            self.assertEqual(db.get_event(event_id)["eventbrite_content_version"], 0)
            self.assertIsNone(db.get_event(event_id)["eventbrite_event_id"])
            db.book_seat(event_id, 1, username="a")
            self.assertEqual(db.get_reservations_for_event(event_id)[0]["source"], "telegram")


if __name__ == "__main__":
    unittest.main()
