import unittest
from unittest.mock import patch

import core.db as db
from bot.handlers.control import bot_pause_command, bot_resume_command, bot_silent_telegram_toggle_command, bot_status_command
from bot.state import runtime_state
from bot.handlers.edit import event_edit_command
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import admin_update, make_context, make_message, make_user


def _info_messages(mock_logger):
    return [c[0][0] for c in mock_logger.info.call_args_list]


class TestAdminCommandAuditLogging(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_admin_commands_logging(self):
        update = admin_update(user=make_user(998877, "admin_boss"))
        context = make_context()

        with as_admin_chat(), patch("bot.handlers.control.logger") as mock_logger:
            await bot_pause_command(update, context)
            self.assertTrue(any("998877" in msg and "paused" in msg for msg in _info_messages(mock_logger)))

            await bot_resume_command(update, context)
            self.assertTrue(any("998877" in msg and "resumed" in msg for msg in _info_messages(mock_logger)))

        ev_id = create_event(title="Log Test Event")
        reply_msg = make_message(text=f"Evento #{ev_id}")
        reply_msg.reply_markup = None
        update.message.reply_to_message = reply_msg
        update.message.text = "/event_edit_title New Glorious Title"

        with as_admin_chat(), patch("bot.handlers.edit.logger") as mock_logger:
            await event_edit_command(update, context)
            self.assertTrue(any("998877" in msg and "title" in msg and f"#{ev_id}" in msg for msg in _info_messages(mock_logger)))
            self.assertEqual(db.get_event(ev_id)["title"], "New Glorious Title")


class TestSilentTelegramToggle(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = patch.object(runtime_state, "telegram_silent", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_toggle_flips_the_flag_and_tells_the_admin(self):
        update = admin_update(user=make_user(998877, "admin_boss"))
        with as_admin_chat(), patch("bot.handlers.control.logger") as mock_logger:
            await bot_silent_telegram_toggle_command(update, make_context())
            self.assertTrue(runtime_state.telegram_silent)
            self.assertIn("ATTIVA", update.message.reply_text.call_args.args[0])
            self.assertTrue(any("998877" in msg and "ON" in msg for msg in _info_messages(mock_logger)))

            await bot_silent_telegram_toggle_command(update, make_context())
            self.assertFalse(runtime_state.telegram_silent)
            self.assertIn("DISATTIVATA", update.message.reply_text.call_args.args[0])

    async def test_status_shows_the_silent_state(self):
        update = admin_update()
        with as_admin_chat():
            await bot_status_command(update, make_context())
            self.assertIn("normale", update.message.reply_text.call_args.args[0])
            runtime_state.telegram_silent = True
            await bot_status_command(update, make_context())
            self.assertIn("SILENZIOSA", update.message.reply_text.call_args.args[0])

    async def test_outsiders_cannot_toggle_it(self):
        update = admin_update()
        with patch("bot.common.auth.config.ADMIN_CHAT_ID", "12345"):
            await bot_silent_telegram_toggle_command(update, make_context())
        self.assertFalse(runtime_state.telegram_silent)


if __name__ == "__main__":
    unittest.main()
