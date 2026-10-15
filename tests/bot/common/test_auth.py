import unittest
from unittest.mock import patch

from bot.common.auth import describe_user
from bot.handlers.control import bot_status_command
from bot.handlers.repost_schedule import event_schedule_list_command
from tests.support.config import patched_config
from tests.support.telegram import make_context, make_update, make_user


class TestDescribeUser(unittest.TestCase):
    def test_describe_user(self):
        self.assertEqual(describe_user(make_user(5, "bob")), "Admin 5 (@bob)")
        self.assertEqual(describe_user(make_user(5, None), role="User"), "User 5")
        self.assertEqual(describe_user(None), "Admin unknown")


class TestAdminOnly(unittest.IsolatedAsyncioTestCase):
    async def test_admin_only_notify_replies_to_outsiders(self):
        update = make_update(chat_id=999)
        with patched_config(ADMIN_CHAT_ID="111"), \
             patch("bot.handlers.repost_schedule.get_all_scheduled_events") as get_all:
            await event_schedule_list_command(update, make_context())
        update.message.reply_text.assert_called_once_with("Non sei autorizzato.")
        get_all.assert_not_called()

    async def test_admin_only_silent_for_outsiders(self):
        update = make_update(chat_id=999)
        with patched_config(ADMIN_CHAT_ID="111"):
            await bot_status_command(update, make_context())
        update.message.reply_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
