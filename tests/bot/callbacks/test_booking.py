import unittest
from datetime import datetime, timedelta

import core.db as db
from bot.callbacks.router import handle_callback_query
from tests.support.config import patched_config
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import callback_update, make_context, make_user

GROUP = "-100777"
USER_CHAT = 1001


class TestReleaseFromPrivateChat(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        stack = patched_config(DISCUSSION_GROUP_ID=GROUP, PUBLIC_CHANNEL_ID="-100555", ADMIN_CHAT_ID="-100999")
        stack.__enter__()
        self.addCleanup(stack.__exit__, None, None, None)
        day = (datetime.now() + timedelta(days=1)).strftime("%d-%m-%Y")
        self.event_id = create_event(status="approved", title="Serata", date=day, normalized_date=day,
                                     max_seats=4, seats="4/4", telegram_message_id=50)
        db.update_discussion_message_info(self.event_id, 60, GROUP)
        self.user = make_user(USER_CHAT, "mario")
        db.book_seat(self.event_id, USER_CHAT, username="mario")
        self.context = make_context()

    async def press(self, data):
        update, query = callback_update(data, chat_id=USER_CHAT, message_id=7, user=self.user)
        query.message.text_html = "⏰ Promemoria"
        await handle_callback_query(update, self.context)
        return query

    def assert_notice_in_the_group_and_discussion_id_kept(self):
        notice = [c.kwargs for c in self.context.bot.send_message.call_args_list
                  if "ha liberato" in c.kwargs.get("text", "")]
        self.assertEqual(notice[0]["chat_id"], int(GROUP))
        self.assertEqual(notice[0]["reply_to_message_id"], 60)
        self.assertEqual(db.get_event(self.event_id)["discussion_message_id"], 60)

    async def test_reminder_button_frees_the_seat(self):
        query = await self.press(f"dmunbook_{self.event_id}")
        self.assertIsNone(db.get_reservation_by_user(self.event_id, user_id=USER_CHAT))
        self.assertIn("Posto liberato", query.edit_message_text.call_args.args[0])
        self.assert_notice_in_the_group_and_discussion_id_kept()

    async def test_event_mine_button_frees_the_seat_and_redraws_the_list(self):
        query = await self.press(f"mineunbook_{self.event_id}")
        self.assertIsNone(db.get_reservation_by_user(self.event_id, user_id=USER_CHAT))
        self.assertIn("Non risulti prenotato", query.edit_message_text.call_args.args[0])
        self.assert_notice_in_the_group_and_discussion_id_kept()

    async def test_nothing_to_release_leaves_the_message_alone(self):
        db.unbook_seat(self.event_id, USER_CHAT)
        query = await self.press(f"dmunbook_{self.event_id}")
        query.edit_message_text.assert_not_awaited()
        self.assertTrue(query.answer.call_args.kwargs["show_alert"])


if __name__ == "__main__":
    unittest.main()
