import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import os
import tempfile
import core.db as db
from core import config


class TestAuditLogging(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_logging.db")
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = self.test_db_path
        db.init_db()

        self.event_data = {
            "title": "Log Test Event",
            "date": "10-10-2026",
            "normalized_date": "10-10-2026",
            "system": "D&D",
            "host": "GameMaster",
            "seats": "1/1",
            "booked_seats": 0,
            "max_seats": 1,
            "description": "Test description",
            "image_path": None,
        }
        self.event_id = db.insert_event(self.event_data, None, "Original text")

    def tearDown(self):
        self.temp_dir.cleanup()
        config.DB_PATH = self.orig_db_path

    async def test_booking_logging_success_and_failure(self):
        from bot.service.booking import handle_seat_booking

        user = MagicMock()
        user.id = 112233
        user.username = "test_player"
        user.first_name = "Player"

        query = MagicMock()
        query.answer = AsyncMock()
        query.message.chat_id = 9999
        query.message.message_id = 100
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        with patch("bot.service.booking.logger") as mock_logger, \
             patch("bot.service.booking.update_event_messages", AsyncMock()):
            await handle_seat_booking(self.event_id, user, query, context)
            mock_logger.info.assert_called()
            info_call = [call[0][0] for call in mock_logger.info.call_args_list]
            self.assertTrue(any("112233" in msg and f"#{self.event_id}" in msg and "booked" in msg for msg in info_call))

            user2 = MagicMock()
            user2.id = 445566
            user2.username = "another_player"
            user2.first_name = "Player2"

            await handle_seat_booking(self.event_id, user2, query, context)
            mock_logger.warning.assert_called()
            warn_call = [call[0][0] for call in mock_logger.warning.call_args_list]
            self.assertTrue(any("445566" in msg and f"#{self.event_id}" in msg and "failed" in msg for msg in warn_call))

    async def test_unbooking_logging_success_and_failure(self):
        from bot.service.booking import handle_seat_booking, handle_seat_unbooking

        user = MagicMock()
        user.id = 112233
        user.username = "test_player"
        user.first_name = "Player"

        query = MagicMock()
        query.answer = AsyncMock()
        query.message.chat_id = 9999
        query.message.message_id = 100
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        with patch("bot.service.booking.update_event_messages", AsyncMock()):
            await handle_seat_booking(self.event_id, user, query, context)

            with patch("bot.service.booking.logger") as mock_logger:
                await handle_seat_unbooking(self.event_id, user, query, context)
                mock_logger.info.assert_called()
                info_call = [call[0][0] for call in mock_logger.info.call_args_list]
                self.assertTrue(any("112233" in msg and f"#{self.event_id}" in msg and "unbooked" in msg for msg in info_call))

                await handle_seat_unbooking(self.event_id, user, query, context)
                mock_logger.warning.assert_called()
                warn_call = [call[0][0] for call in mock_logger.warning.call_args_list]
                self.assertTrue(any("112233" in msg and f"#{self.event_id}" in msg and "failed to unbook" in msg for msg in warn_call))

    async def test_admin_callback_actions_logging(self):
        from bot.callbacks.router import handle_callback_query

        admin = MagicMock()
        admin.id = 998877
        admin.username = "admin_boss"

        query = MagicMock()
        query.from_user = admin
        query.answer = AsyncMock()
        query.edit_message_caption = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.message.caption = "Test Caption"
        query.message.text = None
        query.message.photo = []
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        query.data = f"discard_event_{self.event_id}"
        update = MagicMock()
        update.callback_query = query
        with patch("bot.callbacks.events.logger") as mock_logger:
            await handle_callback_query(update, context)
            mock_logger.info.assert_called()
            info_call = [call[0][0] for call in mock_logger.info.call_args_list]
            self.assertTrue(any("998877" in msg and "discarded" in msg for msg in info_call))

        ev_id2 = db.insert_event(self.event_data, None, "Original text")

        query.data = f"cancel_event_{ev_id2}"
        with patch("bot.callbacks.events.logger") as mock_logger, \
             patch("bot.callbacks.events.send_cancellation_notice", AsyncMock()), \
             patch("bot.callbacks.events.update_event_messages", AsyncMock()):
            await handle_callback_query(update, context)
            info_call = [call[0][0] for call in mock_logger.info.call_args_list]
            self.assertTrue(any("998877" in msg and "cancelled" in msg for msg in info_call))

        query.data = f"reactivate_event_{ev_id2}"
        with patch("bot.callbacks.events.logger") as mock_logger, \
             patch("bot.callbacks.events.send_reactivation_notice", AsyncMock()), \
             patch("bot.callbacks.events.update_event_messages", AsyncMock()):
            await handle_callback_query(update, context)
            info_call = [call[0][0] for call in mock_logger.info.call_args_list]
            self.assertTrue(any("998877" in msg and "reactivated" in msg for msg in info_call))

        query.data = "discard_recap_10-10-2026"
        with patch("bot.callbacks.recap.logger") as mock_logger:
            await handle_callback_query(update, context)
            info_call = [call[0][0] for call in mock_logger.info.call_args_list]
            self.assertTrue(any("998877" in msg and "discarded recap" in msg for msg in info_call))

    async def test_admin_commands_logging(self):
        from bot.handlers.control import bot_pause_command, bot_resume_command
        from bot.handlers.edit import event_edit_command

        admin = MagicMock()
        admin.id = 998877
        admin.username = "admin_boss"

        update = MagicMock()
        update.effective_chat.id = 999
        update.effective_user = admin
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.control.logger") as mock_logger:
            await bot_pause_command(update, context)
            self.assertTrue(any("998877" in msg and "paused" in msg for msg in [c[0][0] for c in mock_logger.info.call_args_list]))

            await bot_resume_command(update, context)
            self.assertTrue(any("998877" in msg and "resumed" in msg for msg in [c[0][0] for c in mock_logger.info.call_args_list]))

        ev_id = db.insert_event(self.event_data, None, "Original text")
        reply_msg = MagicMock()
        reply_msg.text = f"Evento #{ev_id}"
        reply_msg.caption = None
        reply_msg.reply_markup = None
        reply_msg.edit_text = AsyncMock()

        update.message.reply_to_message = reply_msg
        update.message.text = "/event_edit_title New Glorious Title"
        update.message.caption = None

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.edit.logger") as mock_logger:
            await event_edit_command(update, context)
            self.assertTrue(any("998877" in msg and "title" in msg and f"#{ev_id}" in msg for msg in [c[0][0] for c in mock_logger.info.call_args_list]))
            ev = db.get_event(ev_id)
            self.assertEqual(ev["title"], "New Glorious Title")

    async def test_scheduler_logging(self):
        from core.scheduler.archive import archive_today_images, archive_completed_month_logs

        with patch("core.scheduler.archive.logger") as mock_logger:
            await archive_today_images()
            info_calls = [c[0][0] for c in mock_logger.info.call_args_list]
            self.assertTrue(any("archive_today_images" in msg for msg in info_calls))

        with patch("core.scheduler.archive.logger") as mock_logger, \
             patch("core.scheduler.archive.zip_completed_months", return_value=[]):
            await archive_completed_month_logs()
            info_calls = [c[0][0] for c in mock_logger.info.call_args_list]
            self.assertTrue(any("archive_completed_month_logs" in msg for msg in info_calls))

    def test_wordpress_logging(self):
        from core.wordpress import update_article_status

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("core.wordpress.client.requests.post", return_value=mock_resp), \
             patch("core.config.WP_URL", "https://example.com"), \
             patch("core.config.WP_USERNAME", "admin"), \
             patch("core.config.WP_APP_PASSWORD", "pass"), \
             patch("core.wordpress.content.logger") as mock_logger:
            success = update_article_status(1234, "publish")
            self.assertTrue(success)
            info_calls = [c[0][0] for c in mock_logger.info.call_args_list]
            self.assertTrue(any("1234" in msg and "publish" in msg for msg in info_calls))
