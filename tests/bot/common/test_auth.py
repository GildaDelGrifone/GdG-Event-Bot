import unittest
from unittest.mock import patch

from telegram.ext import ApplicationHandlerStop

from bot.common.auth import describe_user, drop_commands_outside_command_chats, is_command_chat
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
    async def test_commands_that_used_to_answer_outsiders_are_silent_too(self):
        update = make_update(chat_id=999)
        with patched_config(ADMIN_CHAT_ID="111"), \
             patch("bot.handlers.repost_schedule.get_all_scheduled_events") as get_all:
            await event_schedule_list_command(update, make_context())
        update.message.reply_text.assert_not_called()
        get_all.assert_not_called()

    async def test_admin_only_silent_for_outsiders(self):
        update = make_update(chat_id=999)
        with patched_config(ADMIN_CHAT_ID="111"):
            await bot_status_command(update, make_context())
        update.message.reply_text.assert_not_called()


class TestCommandChats(unittest.IsolatedAsyncioTestCase):
    def test_only_private_chats_and_the_admin_chat_take_commands(self):
        cases = (
            ("111", "group", True),          # admin chat
            ("12345", "private", True),       # a user's private chat with the bot
            ("-100888", "supergroup", False), # discussion group or any other group
            ("-100777", "channel", False),    # public channel
            ("-100666", "group", False),
        )
        with patched_config(ADMIN_CHAT_ID="111"):
            for chat_id, chat_type, expected in cases:
                with self.subTest(chat_id=chat_id, chat_type=chat_type):
                    self.assertIs(is_command_chat(make_update(chat_id=chat_id, chat_type=chat_type)), expected)

    async def test_commands_outside_command_chats_stop_the_update(self):
        with patched_config(ADMIN_CHAT_ID="111"):
            for chat_id, chat_type in (("-100888", "supergroup"), ("-100777", "channel")):
                with self.subTest(chat_type=chat_type), self.assertRaises(ApplicationHandlerStop):
                    await drop_commands_outside_command_chats(make_update(chat_id=chat_id, chat_type=chat_type), make_context())

            for chat_id, chat_type in (("111", "group"), ("12345", "private")):
                with self.subTest(chat_type=chat_type):
                    self.assertIsNone(await drop_commands_outside_command_chats(make_update(chat_id=chat_id, chat_type=chat_type), make_context()))


if __name__ == "__main__":
    unittest.main()
