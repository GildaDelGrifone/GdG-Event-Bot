import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import BadRequest

from scripts.fix_event_keyboards import fix_keyboards


def event_row(**fields):
    return {"status": "approved", "normalized_date": "25-12-2099", **fields}


class TestFixKeyboardsScript(unittest.IsolatedAsyncioTestCase):
    """fix_keyboards() exits when TELEGRAM_BOT_TOKEN is unset, so every test runs with a dummy token."""

    def setUp(self):
        token_patch = patch("scripts.fix_event_keyboards.TELEGRAM_BOT_TOKEN", "123:dummy-token")
        token_patch.start()
        self.addCleanup(token_patch.stop)

        self.bot = MagicMock()
        self.bot.get_me = AsyncMock(return_value=MagicMock(username="GdG_Event_bot", id=12345))
        self.bot.edit_message_reply_markup = AsyncMock()
        bot_patch = patch("scripts.fix_event_keyboards.Bot", return_value=self.bot)
        bot_patch.start()
        self.addCleanup(bot_patch.stop)

        self.cursor = MagicMock()
        self.cursor.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.return_value = self.cursor
        conn_patch = patch("scripts.fix_event_keyboards.get_connection")
        conn_patch.start().return_value.__enter__.return_value = conn
        self.addCleanup(conn_patch.stop)

    async def test_fix_keyboards_dry_run(self):
        self.cursor.fetchall.return_value = [event_row(
            id=10, title="Catan", telegram_message_id=200, discussion_message_id=300,
            discussion_chat_id="-100111", admin_message_id=400, max_seats=4, booked_seats=1,
        )]

        await fix_keyboards(dry_run=True, delay=0)

        # In dry run, edit_message_reply_markup must not be called
        self.bot.edit_message_reply_markup.assert_not_called()

    async def test_fix_keyboards_filters_approved_status_by_default(self):
        await fix_keyboards(dry_run=True, delay=0)

        query, params = self.cursor.execute.call_args[0]
        self.assertIn("status = ?", query)
        self.assertEqual(params, ("approved",))

    async def test_fix_keyboards_updates_all_targets(self):
        self.cursor.fetchall.return_value = [event_row(
            id=25, title="Wingspan", telegram_message_id=101, discussion_message_id=202,
            discussion_chat_id="-100222", admin_message_id=303, max_seats=5, booked_seats=0,
        )]

        with patch("scripts.fix_event_keyboards.PUBLIC_CHANNEL_ID", "-100999"), \
             patch("scripts.fix_event_keyboards.ADMIN_CHAT_ID", "-100888"):
            await fix_keyboards(dry_run=False, delay=0)

        # Expect 3 calls: channel, discussion, admin
        calls = self.bot.edit_message_reply_markup.call_args_list
        self.assertEqual(self.bot.edit_message_reply_markup.call_count, 3)
        self.assertEqual(calls[0].kwargs["chat_id"], "-100999")
        self.assertEqual(calls[0].kwargs["message_id"], 101)
        self.assertEqual(calls[1].kwargs["chat_id"], -100222)
        self.assertEqual(calls[1].kwargs["message_id"], 202)
        self.assertEqual(calls[2].kwargs["chat_id"], -100888)
        self.assertEqual(calls[2].kwargs["message_id"], 303)

    async def test_fix_keyboards_not_modified_ignored(self):
        self.bot.edit_message_reply_markup.side_effect = BadRequest(
            "Message is not modified: specified new message content and reply markup are exactly the same"
        )
        self.cursor.fetchall.return_value = [event_row(
            id=5, title="Root", telegram_message_id=105, discussion_message_id=None, admin_message_id=None,
        )]

        with patch("scripts.fix_event_keyboards.PUBLIC_CHANNEL_ID", "-100999"):
            # Should not raise exception
            await fix_keyboards(dry_run=False, delay=0)

        self.bot.edit_message_reply_markup.assert_called_once()


if __name__ == "__main__":
    unittest.main()
