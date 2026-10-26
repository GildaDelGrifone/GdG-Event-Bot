import datetime
import unittest
from unittest.mock import MagicMock, patch

from telegram import BotCommandScopeChat, BotCommandScopeDefault, Chat, Message, Update, User
from telegram.error import NetworkError
from telegram.ext import CommandHandler, filters

from main import global_error_handler, main, post_init
from bot.handlers.albums import cache_admin_media_group
from bot.handlers.edit import event_edit_command
from bot.handlers.eventbrite import event_publish_eventbrite_command
from bot.handlers.ingestion import manual_trigger_command
from bot.service.eventbrite_cleanup import delete_cancelled_eventbrite_events
from bot.service.eventbrite_poll import poll_eventbrite_bookings
from tests.support.config import patched_config
from tests.support.telegram import make_bot


class TestGlobalErrorHandler(unittest.IsolatedAsyncioTestCase):
    async def test_network_error_logged_as_warning(self):
        context = MagicMock()
        context.error = NetworkError("Bad Gateway")

        with patch("main.logger") as mock_logger:
            await global_error_handler(MagicMock(), context)
            mock_logger.warning.assert_called_once()
            args, _ = mock_logger.warning.call_args
            self.assertIn("temporaneo", args[0])
            self.assertIn("si risolve automaticamente", args[0])
            self.assertEqual(args[1], context.error)
            mock_logger.error.assert_not_called()

    async def test_general_exception_logged_as_error(self):
        context = MagicMock()
        context.error = ValueError("Something unexpected")

        with patch("main.logger") as mock_logger:
            await global_error_handler(MagicMock(), context)
            mock_logger.error.assert_called_once()
            mock_logger.warning.assert_not_called()
            _, kwargs = mock_logger.error.call_args
            self.assertEqual(kwargs.get("exc_info"), context.error)


class TestHandlerRegistration(unittest.IsolatedAsyncioTestCase):
    def test_caption_command_matching_and_handler_registration(self):
        message = Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=Chat(id=1, type="group"),
            from_user=User(id=1, is_bot=False, first_name="User"),
            caption="/event_edit_image",
        )
        update = Update(update_id=1, message=message)
        self.assertTrue(filters.CaptionRegex(r"^/event_edit_").check_update(update))

        # PTB's CommandHandler only matches message.text, so caption commands need the CaptionRegex handlers
        self.assertFalse(CommandHandler("event_edit_image", lambda u, c: None).check_update(update))

    def test_main_admin_handlers_configured_block_false(self):
        added_handlers = []
        mock_app = MagicMock()
        mock_app.add_handler.side_effect = lambda h, group=0: added_handlers.append((h, group))
        mock_builder = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.connect_timeout.return_value = mock_builder
        mock_builder.read_timeout.return_value = mock_builder
        mock_builder.write_timeout.return_value = mock_builder
        mock_builder.pool_timeout.return_value = mock_builder
        mock_builder.post_init.return_value = mock_builder
        mock_builder.post_shutdown.return_value = mock_builder
        mock_builder.build.return_value = mock_app

        with patch("main.init_db"), \
             patch("main.Application.builder", return_value=mock_builder), \
             patch("main.ADMIN_CHAT_ID", "999"), \
             patch("main.TELEGRAM_BOT_TOKEN", "fake_token"), \
             patched_config(TELEGRAM_BOT_TOKEN="fake_token", ADMIN_CHAT_ID="999"):
            try:
                main()
            except Exception:
                pass

        matched = 0
        for handler, _group in added_handlers:
            cb = getattr(handler, "callback", None)
            if cb in (event_edit_command, manual_trigger_command, cache_admin_media_group):
                self.assertFalse(handler.block, f"Handler {handler} with callback {cb} should have block=False")
                matched += 1

        # event_process, ep, 10 edit commands, CaptionRegex event_edit_, CaptionRegex ep, cache_admin_media_group
        self.assertGreaterEqual(matched, 15)

    async def test_post_init_sets_bot_commands(self):
        mock_app = MagicMock()
        mock_app.bot = make_bot()

        with patch("main.start_scheduler"), patch("main.eventbrite_enabled", return_value=False), \
             patch("main.ADMIN_CHAT_ID", "-100123456"):
            await post_init(mock_app)

        set_commands = mock_app.bot.set_my_commands
        self.assertEqual(set_commands.call_count, 2)

        cmds1, kwargs1 = set_commands.call_args_list[0][0][0], set_commands.call_args_list[0][1]
        self.assertIsInstance(kwargs1.get("scope"), BotCommandScopeDefault)
        self.assertTrue(any(c.command == "start" for c in cmds1))

        cmds2, kwargs2 = set_commands.call_args_list[1][0][0], set_commands.call_args_list[1][1]
        self.assertIsInstance(kwargs2.get("scope"), BotCommandScopeChat)
        self.assertEqual(kwargs2["scope"].chat_id, -100123456)
        cmd_names = [c.command for c in cmds2]
        self.assertIn("event_next", cmd_names)
        self.assertIn("event_edit_title", cmd_names)
        self.assertIn("event_edit_date", cmd_names)
        self.assertNotIn("event_edit_normalized_date", cmd_names)

        publish_cmd = next(c for c in cmds2 if c.command == "event_publish_eventbrite")
        self.assertEqual(publish_cmd.description, "[ID] Pubblica l'evento su Eventbrite")

        title_cmd = next(c for c in cmds2 if c.command == "event_edit_title")
        self.assertIn("<Titolo>", title_cmd.description)
        date_cmd = next(c for c in cmds2 if c.command == "event_edit_date")
        self.assertIn("<DD-MM-YYYY HH:MM>", date_cmd.description)


class TestRequiredSettings(unittest.TestCase):
    def test_main_exits_before_building_the_app_when_required_settings_are_missing(self):
        with patch("main.init_db") as init_db, patch("main.Application.builder") as builder, \
             patch("main.logger") as mock_logger, patched_config(TELEGRAM_BOT_TOKEN=None, ADMIN_CHAT_ID=None):
            main()
        builder.assert_not_called()
        init_db.assert_not_called()
        self.assertIn("TELEGRAM_BOT_TOKEN, ADMIN_CHAT_ID", mock_logger.error.call_args.args[0])


class TestEventbriteWiring(unittest.IsolatedAsyncioTestCase):
    async def test_poller_is_scheduled_only_when_eventbrite_is_enabled(self):
        for enabled, expected_calls in ((True, 1), (False, 0)):
            with self.subTest(enabled=enabled):
                mock_app = MagicMock()
                mock_app.bot = make_bot()
                with patch("main.start_scheduler"), patch("main.add_interval_job") as add_job, \
                     patch("main.add_cron_job") as add_cron, \
                     patch("main.eventbrite_enabled", return_value=enabled), \
                     patch("main.config.EVENTBRITE_POLL_MINUTES", 5), patch("main.ADMIN_CHAT_ID", None):
                    await post_init(mock_app)

                self.assertEqual(add_job.call_count, expected_calls)
                self.assertEqual(add_cron.call_count, expected_calls)
                if enabled:
                    add_job.assert_called_once_with(poll_eventbrite_bookings, 5, [mock_app.bot])
                    add_cron.assert_called_once_with(delete_cancelled_eventbrite_events, 23, 59, [mock_app.bot])

    async def test_post_init_starts_the_scheduler_before_adding_the_poller(self):
        mock_app = MagicMock()
        mock_app.bot = make_bot()
        calls = MagicMock()
        with patch("main.start_scheduler", calls.start), patch("main.add_interval_job", calls.add), \
             patch("main.add_cron_job", calls.cron), \
             patch("main.eventbrite_enabled", return_value=True), patch("main.ADMIN_CHAT_ID", None):
            await post_init(mock_app)
        self.assertEqual([c[0] for c in calls.mock_calls], ["start", "add", "cron"])

    def test_publish_command_is_registered_for_text_and_caption(self):
        added = []
        mock_app = MagicMock()
        mock_app.add_handler.side_effect = lambda h, group=0: added.append(h)
        mock_builder = MagicMock()
        for name in ("token", "connect_timeout", "read_timeout", "write_timeout", "pool_timeout", "post_init", "post_shutdown"):
            getattr(mock_builder, name).return_value = mock_builder
        mock_builder.build.return_value = mock_app

        with patch("main.init_db"), patch("main.Application.builder", return_value=mock_builder), \
             patch("main.TELEGRAM_BOT_TOKEN", "fake_token"), \
             patched_config(TELEGRAM_BOT_TOKEN="fake_token", ADMIN_CHAT_ID="999"):
            try:
                main()
            except Exception:
                pass

        ours = [h for h in added if getattr(h, "callback", None) is event_publish_eventbrite_command]
        self.assertEqual(len(ours), 2)
        self.assertTrue(all(h.block is False for h in ours))
        command = next(h for h in ours if isinstance(h, CommandHandler))
        self.assertIn("event_publish_eventbrite", command.commands)
        caption = next(h for h in ours if not isinstance(h, CommandHandler))
        self.assertIn("event_publish_eventbrite", caption.filters.pattern.pattern)


if __name__ == "__main__":
    unittest.main()
