import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from unittest.mock import patch

from core.log_utils import DailyMonthlyLogHandler, zip_completed_months


class TestLogUtils(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.test_dir = temp_dir.name

    def _write(self, filename, content):
        path = os.path.join(self.test_dir, filename)
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(content)
        return path

    def test_zip_completed_months_archives_past_months_only(self):
        f_jul1 = self._write("bot.log.2026-07-01", "July 1 log content")
        f_jul2 = self._write("bot.log.2026-07-31", "July 31 log content")
        f_aug1 = self._write("bot.log.2026-08-01", "August 1 log content")
        f_aug2 = self._write("bot.log.2026-08-15", "August 15 log content")
        f_active = self._write("bot.log", "Active current log content")
        f_other = self._write("notes.txt", "Some notes")

        archived = zip_completed_months(self.test_dir, current_date=datetime(2026, 8, 20))

        expected_zip = os.path.join(self.test_dir, "bot_logs_2026-07.zip")
        self.assertEqual(archived, [expected_zip])
        self.assertTrue(os.path.exists(expected_zip))

        with zipfile.ZipFile(expected_zip, "r") as zf:
            self.assertEqual(set(zf.namelist()), {"bot.log.2026-07-01", "bot.log.2026-07-31"})
            self.assertEqual(zf.read("bot.log.2026-07-01").decode("utf-8"), "July 1 log content")
            self.assertEqual(zf.read("bot.log.2026-07-31").decode("utf-8"), "July 31 log content")

        self.assertFalse(os.path.exists(f_jul1))
        self.assertFalse(os.path.exists(f_jul2))
        # Current month files and active log must remain untouched
        self.assertTrue(os.path.exists(f_aug1))
        self.assertTrue(os.path.exists(f_aug2))
        self.assertTrue(os.path.exists(f_active))
        self.assertTrue(os.path.exists(f_other))

    def test_zip_completed_months_cross_year(self):
        f_dec = self._write("bot.log.2025-12-31", "Dec 2025")
        f_jan = self._write("bot.log.2026-01-01", "Jan 2026")

        archived = zip_completed_months(self.test_dir, current_date=datetime(2026, 1, 2))

        self.assertEqual(archived, [os.path.join(self.test_dir, "bot_logs_2025-12.zip")])
        self.assertFalse(os.path.exists(f_dec))
        self.assertTrue(os.path.exists(f_jan))

    def test_zip_completed_months_appends_to_existing_zip_without_duplication(self):
        self._write("bot.log.2026-07-01", "July 1")
        zip_completed_months(self.test_dir, current_date=datetime(2026, 8, 1))

        self._write("bot.log.2026-07-02", "July 2")
        archived = zip_completed_months(self.test_dir, current_date=datetime(2026, 8, 2))

        expected_zip = os.path.join(self.test_dir, "bot_logs_2026-07.zip")
        self.assertEqual(archived, [expected_zip])
        with zipfile.ZipFile(expected_zip, "r") as zf:
            self.assertEqual(set(zf.namelist()), {"bot.log.2026-07-01", "bot.log.2026-07-02"})

    def test_zip_completed_months_nonexistent_directory(self):
        self.assertEqual(zip_completed_months(os.path.join(self.test_dir, "does_not_exist")), [])

    def test_handler_rollover_triggers_check_and_zip(self):
        handler = DailyMonthlyLogHandler(os.path.join(self.test_dir, "bot.log"), when="midnight", backupCount=0)
        self.addCleanup(handler.close)

        with patch.object(handler, "check_and_zip") as mock_check, \
             patch("logging.handlers.TimedRotatingFileHandler.doRollover"):
            handler.doRollover()
            mock_check.assert_called_once()


if __name__ == "__main__":
    unittest.main()
