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


if __name__ == "__main__":
    unittest.main()
