import os
import shutil
import tempfile
import unittest
import zipfile
from datetime import datetime
from unittest.mock import patch, MagicMock

from core.log_utils import zip_completed_months, DailyMonthlyLogHandler


class TestLogUtils(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_zip_completed_months_archives_past_months_only(self):
        # Create dummy log files for:
        # - Past month: July 2026 (2026-07-01, 2026-07-31)
        # - Current month: August 2026 (2026-08-01, 2026-08-15)
        # - Active log: bot.log
        # - Unrelated file: notes.txt
        f_jul1 = os.path.join(self.test_dir, "bot.log.2026-07-01")
        f_jul2 = os.path.join(self.test_dir, "bot.log.2026-07-31")
        f_aug1 = os.path.join(self.test_dir, "bot.log.2026-08-01")
        f_aug2 = os.path.join(self.test_dir, "bot.log.2026-08-15")
        f_active = os.path.join(self.test_dir, "bot.log")
        f_other = os.path.join(self.test_dir, "notes.txt")

        for f, content in [
            (f_jul1, "July 1 log content"),
            (f_jul2, "July 31 log content"),
            (f_aug1, "August 1 log content"),
            (f_aug2, "August 15 log content"),
            (f_active, "Active current log content"),
            (f_other, "Some notes"),
        ]:
            with open(f, "w", encoding="utf-8") as fp:
                fp.write(content)

        # Assume current date is August 20, 2026
        current_date = datetime(2026, 8, 20)
        archived = zip_completed_months(self.test_dir, current_date=current_date)

        expected_zip = os.path.join(self.test_dir, "bot_logs_2026-07.zip")
        self.assertEqual(archived, [expected_zip])
        self.assertTrue(os.path.exists(expected_zip))

        # Check zip contents
        with zipfile.ZipFile(expected_zip, "r") as zf:
            names = set(zf.namelist())
            self.assertEqual(names, {"bot.log.2026-07-01", "bot.log.2026-07-31"})
            self.assertEqual(zf.read("bot.log.2026-07-01").decode("utf-8"), "July 1 log content")
            self.assertEqual(zf.read("bot.log.2026-07-31").decode("utf-8"), "July 31 log content")

        # Past month uncompressed files must be removed
        self.assertFalse(os.path.exists(f_jul1))
        self.assertFalse(os.path.exists(f_jul2))

        # Current month files and active log must remain untouched
        self.assertTrue(os.path.exists(f_aug1))
        self.assertTrue(os.path.exists(f_aug2))
        self.assertTrue(os.path.exists(f_active))
        self.assertTrue(os.path.exists(f_other))

    def test_zip_completed_months_cross_year(self):
        # December 2025 logs when current date is January 2026
        f_dec = os.path.join(self.test_dir, "bot.log.2025-12-31")
        f_jan = os.path.join(self.test_dir, "bot.log.2026-01-01")
        with open(f_dec, "w", encoding="utf-8") as fp:
            fp.write("Dec 2025")
        with open(f_jan, "w", encoding="utf-8") as fp:
            fp.write("Jan 2026")

        current_date = datetime(2026, 1, 2)
        archived = zip_completed_months(self.test_dir, current_date=current_date)

        expected_zip = os.path.join(self.test_dir, "bot_logs_2025-12.zip")
        self.assertEqual(archived, [expected_zip])
        self.assertFalse(os.path.exists(f_dec))
        self.assertTrue(os.path.exists(f_jan))

    def test_zip_completed_months_appends_to_existing_zip_without_duplication(self):
        f_jul1 = os.path.join(self.test_dir, "bot.log.2026-07-01")
        with open(f_jul1, "w", encoding="utf-8") as fp:
            fp.write("July 1")

        zip_completed_months(self.test_dir, current_date=datetime(2026, 8, 1))

        # Add another July file later
        f_jul2 = os.path.join(self.test_dir, "bot.log.2026-07-02")
        with open(f_jul2, "w", encoding="utf-8") as fp:
            fp.write("July 2")

        archived = zip_completed_months(self.test_dir, current_date=datetime(2026, 8, 2))
        expected_zip = os.path.join(self.test_dir, "bot_logs_2026-07.zip")
        self.assertEqual(archived, [expected_zip])

        with zipfile.ZipFile(expected_zip, "r") as zf:
            self.assertEqual(set(zf.namelist()), {"bot.log.2026-07-01", "bot.log.2026-07-02"})

    def test_zip_completed_months_nonexistent_directory(self):
        non_existent = os.path.join(self.test_dir, "does_not_exist")
        result = zip_completed_months(non_existent)
        self.assertEqual(result, [])

    def test_handler_rollover_triggers_check_and_zip(self):
        log_file = os.path.join(self.test_dir, "bot.log")
        handler = DailyMonthlyLogHandler(log_file, when="midnight", backupCount=0)

        with patch.object(handler, "check_and_zip") as mock_check:
            with patch("logging.handlers.TimedRotatingFileHandler.doRollover"):
                handler.doRollover()
                mock_check.assert_called_once()

        handler.close()


class TestSchedulerLogArchiving(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_archive_completed_month_logs(self):
        from core.scheduler.archive import archive_completed_month_logs
        with patch("core.scheduler.archive.zip_completed_months") as mock_zip:
            mock_zip.return_value = ["/path/to/bot_logs_2026-08.zip"]
            await archive_completed_month_logs()
            mock_zip.assert_called_once()
