import unittest
from unittest.mock import patch

import core.db as db
from bot.handlers.control import bot_pause_command, bot_resume_command
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


if __name__ == "__main__":
    unittest.main()
