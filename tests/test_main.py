import datetime
import unittest
from unittest.mock import MagicMock, patch

from telegram import BotCommandScopeChat, BotCommandScopeDefault, Chat, Message, Update, User
from telegram.error import NetworkError
from telegram.ext import CommandHandler, filters

from main import global_error_handler, main, post_init
from bot.handlers.albums import cache_admin_media_group
from bot.handlers.edit import event_edit_command
from bot.handlers.ingestion import manual_trigger_command
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
        mock_builder.post_init.return_value = mock_builder
        mock_builder.post_shutdown.return_value = mock_builder
        mock_builder.build.return_value = mock_app

        with patch("main.init_db"), \
             patch("main.Application.builder", return_value=mock_builder), \
             patch("main.ADMIN_CHAT_ID", "999"), \
             patch("main.TELEGRAM_BOT_TOKEN", "fake_token"):
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

        with patch("main.start_scheduler"), patch("main.ADMIN_CHAT_ID", "-100123456"):
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

        title_cmd = next(c for c in cmds2 if c.command == "event_edit_title")
        self.assertIn("<Titolo>", title_cmd.description)
        date_cmd = next(c for c in cmds2 if c.command == "event_edit_date")
        self.assertIn("<DD-MM-YYYY HH:MM>", date_cmd.description)


if __name__ == "__main__":
    unittest.main()
