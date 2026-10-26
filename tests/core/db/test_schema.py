import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import core.db as db
import core.db.schema as schema
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


class TestScheduledEventsSchema(unittest.TestCase):
    def test_init_db_adds_advance_days_to_an_old_scheduled_events_table(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        legacy_db_path = os.path.join(temp_dir.name, "legacy.db")
        with sqlite3.connect(legacy_db_path) as conn:
            conn.execute("CREATE TABLE scheduled_events (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT)")
            conn.execute("INSERT INTO scheduled_events (title) VALUES ('old')")

        with patched_config(DB_PATH=legacy_db_path):
            db.init_db()
        with sqlite3.connect(legacy_db_path) as conn:
            self.assertEqual(conn.execute("SELECT advance_days FROM scheduled_events").fetchone(), (0,))


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


class TestSchemaVersioning(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.db_path = os.path.join(temp_dir.name, "versioned.db")

    def pragma(self, name):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(f"PRAGMA {name}").fetchone()[0]

    def test_init_db_enables_wal_and_records_the_schema_version(self):
        with patched_config(DB_PATH=self.db_path):
            db.init_db()
        self.assertEqual(self.pragma("journal_mode"), "wal")
        self.assertEqual(self.pragma("user_version"), schema.SCHEMA_VERSION)

    def test_versioned_migrations_run_once_and_in_order(self):
        v1 = schema.SCHEMA_VERSION + 1
        v2 = schema.SCHEMA_VERSION + 2
        migrations = {
            v1: ("CREATE TABLE marker (step INTEGER)", "INSERT INTO marker VALUES (1)"),
            v2: ("INSERT INTO marker VALUES (2)",),
        }
        with patched_config(DB_PATH=self.db_path):
            db.init_db()
            with patch.object(schema, "VERSIONED_MIGRATIONS", migrations), patch.object(schema, "SCHEMA_VERSION", v2):
                db.init_db()
                db.init_db()
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual([r[0] for r in conn.execute("SELECT step FROM marker")], [1, 2])
        self.assertEqual(self.pragma("user_version"), v2)

    def test_migration_v2_converts_absolute_data_image_paths_to_relative(self):
        with sqlite3.connect(self.db_path) as conn:
            for ddl in schema.TABLES:
                conn.execute(ddl)
            conn.execute(
                "INSERT INTO events (title, image_path) VALUES (?, ?), (?, ?)",
                ("Host Ev", "/home/user/bot/data/2026/10/26/event_1.jpg", "Pod Ev", "/app/data/2026/10/26/event_2.jpg"),
            )
            conn.execute(
                "INSERT INTO scheduled_events (title, text, image_path) VALUES (?, ?, ?), (?, ?, ?)",
                ("Host Sched", "t", "/home/user/bot/data/scheduled/sched_1.jpg", "Pod Sched", "t", "/app/data/scheduled/sched_2.jpg"),
            )
            conn.execute("PRAGMA user_version = 1")

        with patched_config(DB_PATH=self.db_path):
            db.init_db()

        with sqlite3.connect(self.db_path) as conn:
            ev_paths = [r[0] for r in conn.execute("SELECT image_path FROM events ORDER BY id")]
            sched_paths = [r[0] for r in conn.execute("SELECT image_path FROM scheduled_events ORDER BY id")]
        self.assertEqual(ev_paths, ["data/2026/10/26/event_1.jpg", "data/2026/10/26/event_2.jpg"])
        self.assertEqual(sched_paths, ["data/scheduled/sched_1.jpg", "data/scheduled/sched_2.jpg"])


if __name__ == "__main__":
    unittest.main()
