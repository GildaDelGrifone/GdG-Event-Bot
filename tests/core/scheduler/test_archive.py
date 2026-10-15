import unittest
from datetime import datetime
from unittest.mock import patch

import core.db as db

from core.scheduler.archive import archive_completed_month_logs, archive_today_images
from tests.support.config import patched_config
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import make_bot


def _info_messages(mock_logger):
    return [c[0][0] for c in mock_logger.info.call_args_list]


class TestArchiveAuditLogging(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_logging(self):
        # DATA_DIR points at the temp dir so the job never zips real event images
        with patched_config(DATA_DIR=self.temp_dir.name), patch("core.scheduler.archive.logger") as mock_logger:
            await archive_today_images()
            self.assertTrue(any("archive_today_images" in msg for msg in _info_messages(mock_logger)))

        with patch("core.scheduler.archive.logger") as mock_logger, \
             patch("core.scheduler.archive.zip_completed_months", return_value=[]):
            await archive_completed_month_logs()
            self.assertTrue(any("archive_completed_month_logs" in msg for msg in _info_messages(mock_logger)))


class TestArchiveTodayImages(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def _approved_event(self, title, display_date, day, channel_msg_id, discussion_msg_id, **fields):
        event_id = create_event(status="approved", title=title, date=display_date, normalized_date=day, max_seats=4,
                                description="Descrizione", **fields)
        db.update_telegram_message_info(event_id, channel_msg_id, f"https://t.me/c/123/{channel_msg_id}")
        db.update_discussion_message_info(event_id, discussion_msg_id, "-100999999")
        return event_id

    async def test_archive_today_images_disables_booking_for_today_events(self):
        today_str = datetime.now().strftime("%d-%m-%Y")
        # Today's approved event and a future one, both with channel and discussion messages
        self._approved_event("Evento Oggi", f"Oggi {today_str}", today_str, 1001, 2001, original_text="raw 1", system="D&D", host="Master")
        self._approved_event("Evento Futuro", "Domani 30-12-2099", "30-12-2099", 1002, 2002, original_text="raw 2", system="Pathfinder",
                             host="Master 2")
        bot = make_bot()

        # DATA_DIR points at the temp dir so the job never zips real event images
        with patched_config(PUBLIC_CHANNEL_ID="-100123456", DISCUSSION_GROUP_ID="-100999999",
                            DATA_DIR=self.temp_dir.name):
            await archive_today_images(bot=bot)

        calls = bot.edit_message_reply_markup.call_args_list
        edited_msgs = [c.kwargs.get("message_id") for c in calls]
        self.assertIn(1001, edited_msgs)
        self.assertIn(2001, edited_msgs)
        self.assertNotIn(1002, edited_msgs)
        self.assertNotIn(2002, edited_msgs)

        for c in calls:
            self.assertIsNone(c.kwargs.get("reply_markup"))

    async def test_archive_today_images_without_bot_succeeds(self):
        with patched_config(DATA_DIR=self.temp_dir.name):
            await archive_today_images(bot=None)


class TestSchedulerLogArchiving(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_archive_completed_month_logs(self):
        with patch("core.scheduler.archive.zip_completed_months") as mock_zip:
            mock_zip.return_value = ["/path/to/bot_logs_2026-08.zip"]
            await archive_completed_month_logs()
            mock_zip.assert_called_once()


if __name__ == "__main__":
    unittest.main()
