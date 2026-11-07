import gzip
import os
import sqlite3
import unittest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from core.scheduler import backup
from tests.support.config import patched_config
from tests.support.db import TempDBMixin, create_event


def _restored_titles(gz_path, temp_dir):
    restored = os.path.join(temp_dir, "restored.db")
    with gzip.open(gz_path, "rb") as src, open(restored, "wb") as dst:
        dst.write(src.read())
    conn = sqlite3.connect(restored)
    try:
        return [row[0] for row in conn.execute("SELECT title FROM events ORDER BY id")]
    finally:
        conn.close()


class TestBackupDatabase(TempDBMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.data_dir = os.path.join(self.temp_dir.name, "data")
        stack = patched_config(DATA_DIR=self.data_dir, DB_BACKUP_DAYS=7, DB_BACKUP_WEEKS=4)
        stack.__enter__()
        self.addCleanup(stack.__exit__, None, None, None)

    def test_writes_a_gzipped_copy_with_the_live_rows(self):
        create_event(title="Prima")
        create_event(title="Seconda")
        path = backup.backup_database(today=date(2026, 11, 7))
        self.assertEqual(os.path.basename(path), "bot_database_2026-11-07.db.gz")
        self.assertEqual(_restored_titles(path, self.temp_dir.name), ["Prima", "Seconda"])
        self.assertEqual(os.listdir(backup.backups_dir()), ["bot_database_2026-11-07.db.gz"])

    def test_same_day_backup_is_overwritten(self):
        create_event(title="Prima")
        backup.backup_database(today=date(2026, 11, 7))
        create_event(title="Seconda")
        path = backup.backup_database(today=date(2026, 11, 7))
        self.assertEqual(len(backup.list_backups()), 1)
        self.assertEqual(_restored_titles(path, self.temp_dir.name), ["Prima", "Seconda"])

    def test_failed_integrity_check_keeps_previous_backups(self):
        old = backup.backup_database(today=date(2026, 11, 6))
        with patch.object(backup, "_snapshot", side_effect=RuntimeError("integrity check failed")):
            with self.assertRaises(RuntimeError):
                backup.backup_database(today=date(2026, 11, 7))
        self.assertEqual(os.listdir(backup.backups_dir()), [os.path.basename(old)])

    def test_disabled_with_zero_days(self):
        with patched_config(DB_BACKUP_DAYS=0):
            self.assertIsNone(backup.backup_database())
        self.assertFalse(os.path.exists(backup.backups_dir()))

    def test_old_copies_are_pruned(self):
        directory = backup.backups_dir()
        os.makedirs(directory)
        start = date(2026, 9, 1)
        for offset in range(60):
            open(os.path.join(directory, f"bot_database_{start + timedelta(days=offset):%Y-%m-%d}.db.gz"), "w").close()
        backup.backup_database(today=start + timedelta(days=60))
        self.assertEqual(len(backup.list_backups()), backup.prune_backups(directory, 7, 4))
        self.assertLessEqual(len(backup.list_backups()), 11)


class TestRotation(unittest.TestCase):
    def test_keeps_newest_days_and_first_backup_of_recent_weeks(self):
        days = [date(2026, 10, 1) + timedelta(days=i) for i in range(40)]  # 1 Oct .. 9 Nov
        keep = backup.backups_to_keep(days, keep_days=7, keep_weeks=4)
        self.assertTrue(set(days[-7:]) <= keep)
        weekly = sorted(keep - set(days[-7:]))
        self.assertTrue(all(day.weekday() == 0 for day in weekly))  # Mondays: first backup of each ISO week
        self.assertLessEqual(len(keep), 11)

    def test_prune_leaves_other_files_alone(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            for name in ("bk_db.zip", "notes.txt", "bot_database_2026-01-01.db.gz", "bot_database_2026-01-02.db.gz"):
                open(os.path.join(directory, name), "w").close()
            kept = backup.prune_backups(directory, keep_days=1, keep_weeks=0)
            self.assertEqual(kept, 1)
            self.assertEqual(sorted(os.listdir(directory)),
                             ["bk_db.zip", "bot_database_2026-01-02.db.gz", "notes.txt"])


class TestOffsiteCopies(unittest.TestCase):
    def test_off_without_a_bucket(self):
        with patched_config(DB_BACKUP_R2_BUCKET=""), patch.object(backup, "upload_file") as upload:
            self.assertIsNone(backup.upload_backup_offsite("/x/bot_database_2026-11-07.db.gz"))
        upload.assert_not_called()

    def test_the_public_media_bucket_is_refused(self):
        with patched_config(DB_BACKUP_R2_BUCKET="gdg-media", R2_BUCKET="gdg-media"), \
             patch.object(backup, "upload_file") as upload:
            with self.assertRaises(RuntimeError):
                backup.upload_backup_offsite("/x/bot_database_2026-11-07.db.gz")
        upload.assert_not_called()

    def test_uploads_then_rotates_the_remote_copies(self):
        start = date(2026, 9, 1)
        keys = [f"backups/bot_database_{start + timedelta(days=i):%Y-%m-%d}.db.gz" for i in range(61)]
        keys.append("backups/notes.txt")
        with patched_config(DB_BACKUP_R2_BUCKET="gdg-backups", DB_BACKUP_DAYS=7, DB_BACKUP_WEEKS=4), \
             patch.object(backup, "upload_file") as upload, \
             patch.object(backup, "list_keys", return_value=keys), \
             patch.object(backup, "delete_key") as delete:
            kept = backup.upload_backup_offsite("/x/bot_database_2026-10-31.db.gz")
        upload.assert_called_once_with("/x/bot_database_2026-10-31.db.gz",
                                       "backups/bot_database_2026-10-31.db.gz", "gdg-backups")
        deleted = {call.args[0] for call in delete.call_args_list}
        self.assertEqual(len(keys) - 1 - len(deleted), kept)
        self.assertNotIn("backups/notes.txt", deleted)
        self.assertNotIn(keys[60], deleted)
        self.assertTrue(all(call.args[1] == "gdg-backups" for call in delete.call_args_list))


class TestRunDatabaseBackup(unittest.IsolatedAsyncioTestCase):
    async def test_failure_notifies_the_admins(self):
        bot = MagicMock(send_message=AsyncMock())
        with patched_config(ADMIN_CHAT_ID="999"), \
             patch.object(backup, "backup_database", side_effect=OSError("disk full")):
            await backup.run_database_backup(bot)
        bot.send_message.assert_awaited_once()
        self.assertIn("disk full", bot.send_message.call_args.kwargs["text"])

    async def test_success_sends_nothing(self):
        bot = MagicMock(send_message=AsyncMock())
        with patch.object(backup, "backup_database", return_value="/x.db.gz"), \
             patch.object(backup, "upload_backup_offsite", return_value=11) as upload:
            await backup.run_database_backup(bot)
        upload.assert_called_once_with("/x.db.gz")
        bot.send_message.assert_not_awaited()

    async def test_offsite_failure_is_reported_separately(self):
        bot = MagicMock(send_message=AsyncMock())
        with patched_config(ADMIN_CHAT_ID="999"), \
             patch.object(backup, "backup_database", return_value="/x.db.gz"), \
             patch.object(backup, "upload_backup_offsite", side_effect=RuntimeError("AccessDenied")):
            await backup.run_database_backup(bot)
        text = bot.send_message.call_args.kwargs["text"]
        self.assertIn("AccessDenied", text)
        self.assertIn("backup locale è stato salvato", text)

    async def test_no_offsite_copy_when_the_local_backup_failed(self):
        bot = MagicMock(send_message=AsyncMock())
        with patched_config(ADMIN_CHAT_ID="999"), \
             patch.object(backup, "backup_database", side_effect=OSError("disk full")), \
             patch.object(backup, "upload_backup_offsite") as upload:
            await backup.run_database_backup(bot)
        upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
