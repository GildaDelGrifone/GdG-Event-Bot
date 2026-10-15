import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.scheduler.recap import generate_daily_recap
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin
from tests.support.images import image_file
from tests.support.telegram import make_bot


class TestRecapImageRecompression(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.temp_dir = temp_dir.name

    async def test_scheduler_emergency_recompression_on_photo_invalid_dimensions(self):
        mock_bot = make_bot()
        mock_bot.send_photo = AsyncMock(side_effect=[
            Exception("Bad Request: Photo_invalid_dimensions"),
            MagicMock(message_id=999),
        ])

        dummy_event = {
            "id": 101,
            "title": "Big Event",
            "system": "D&D",
            "status": "approved",
            "normalized_date": "07-10-2026",
            "booked_seats": 2,
            "max_seats": 5,
            "image_path": image_file(self.temp_dir, "event.jpg", 1000, 1000),
        }

        with patch("core.scheduler.recap.get_pending_events_for_recap", return_value=[dummy_event]), \
             patch("core.scheduler.recap.mark_events_as_recap"):
            res = await generate_daily_recap(mock_bot, manual_date="07-10-2026", is_manual=True)
            self.assertTrue(res)

            self.assertEqual(mock_bot.send_photo.call_count, 2)
            mock_bot.send_message.assert_not_called()


class TestAutomaticRecap(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_generate_daily_recap_automatic_silent_when_no_events(self):
        bot = make_bot()

        with as_admin_chat(), patch("core.scheduler.recap.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 0
            mock_now.strftime.side_effect = lambda fmt: "01-01-2099" if "%d" in fmt else "Monday"
            mock_dt.now.return_value = mock_now

            res = await generate_daily_recap(bot, is_manual=False)

        self.assertFalse(res)
        bot.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
