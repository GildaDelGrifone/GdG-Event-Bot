import unittest
from unittest.mock import patch

import core.db as db
from bot.callbacks.router import handle_callback_query
from tests.support.config import patched_config
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import callback_update, make_context, make_user

GROUP = "-100777"


class TestWaitlistFlow(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    """Full event: B queues with ⏳ Lista d'attesa; when A frees the seat, B gets it and is told."""

    def setUp(self):
        super().setUp()
        stack = patched_config(DISCUSSION_GROUP_ID=GROUP, PUBLIC_CHANNEL_ID="-100555")
        stack.__enter__()
        self.addCleanup(stack.__exit__, None, None, None)
        self.event_id = create_event(status="approved", seats="1/1", max_seats=1, telegram_message_id=50)
        db.update_discussion_message_info(self.event_id, 60, GROUP)
        self.anna, self.bruno = make_user(1, "anna"), make_user(2, "bruno")
        self.context = make_context()
        self.assertTrue(db.book_seat(self.event_id, 1, username="anna")[0])

    async def press(self, data, user):
        update, query = callback_update(data, chat_id=int(GROUP), message_id=60, user=user)
        await handle_callback_query(update, self.context)
        return query

    def sent_texts(self):
        return [call.kwargs.get("text", "") for call in self.context.bot.send_message.call_args_list]

    async def test_full_button_joins_and_shows_the_queue_on_the_post(self):
        query = await self.press(f"full_{self.event_id}", self.bruno)
        self.assertIn("posizione 1", query.answer.call_args.args[0])
        self.assertEqual(db.waitlist_position(self.event_id, 2), 1)
        bot = self.context.bot
        edits = [c.kwargs.get("text") or c.kwargs.get("caption") or ""
                 for c in bot.edit_message_text.call_args_list + bot.edit_message_caption.call_args_list]
        self.assertTrue(any("In attesa: 1" in text for text in edits))

        query = await self.press(f"full_{self.event_id}", self.bruno)
        self.assertIn("già in lista", query.answer.call_args.args[0])

    async def test_a_freed_seat_goes_to_the_first_in_line(self):
        await self.press(f"full_{self.event_id}", self.bruno)
        await self.press(f"unbook_{self.event_id}", self.anna)

        self.assertIsNone(db.get_reservation_by_user(self.event_id, user_id=1))
        self.assertEqual(db.get_reservation_by_user(self.event_id, user_id=2)["seats_booked"], 1)
        self.assertEqual(db.waitlist_count(self.event_id), 0)
        texts = self.sent_texts()
        self.assertTrue(any("@bruno lo prende dalla lista d'attesa" in t for t in texts))
        dm = [c for c in self.context.bot.send_message.call_args_list if c.kwargs.get("chat_id") == 2]
        self.assertEqual(len(dm), 1)

    async def test_annulla_takes_a_queued_user_off_the_list(self):
        await self.press(f"full_{self.event_id}", self.bruno)
        query = await self.press(f"unbook_{self.event_id}", self.bruno)
        self.assertEqual(query.answer.call_args.args[0], "Sei uscito dalla lista d'attesa.")
        self.assertEqual(db.waitlist_count(self.event_id), 0)
        self.assertEqual(db.get_reservation_by_user(self.event_id, user_id=1)["seats_booked"], 1)

    async def test_an_old_prenota_button_cannot_jump_the_queue(self):
        db.join_waitlist(self.event_id, 2, username="bruno")
        db.unbook_seat(self.event_id, 1)  # freed outside update_event_messages: the queue still holds bruno
        await self.press(f"book_{self.event_id}", make_user(3, "carla"))
        self.assertEqual(db.get_reservation_by_user(self.event_id, user_id=2)["seats_booked"], 1)
        self.assertIsNone(db.get_reservation_by_user(self.event_id, user_id=3))
        self.assertEqual(db.waitlist_position(self.event_id, 3), 1)

    async def test_an_admin_removal_also_promotes(self):
        await self.press(f"full_{self.event_id}", self.bruno)
        reservation = db.get_reservation_by_user(self.event_id, user_id=1)
        with patch("bot.callbacks.subscribers.send_admin_action_notice"):
            await self.press(f"sub_dec_{self.event_id}_{reservation['id']}", make_user())
        self.assertEqual(db.get_reservation_by_user(self.event_id, user_id=2)["seats_booked"], 1)

    async def test_a_private_table_says_sold_out_and_queues_nobody(self):
        private = create_event(status="approved", seats="0/0 Completo", max_seats=0, telegram_message_id=51)
        update, query = callback_update(f"full_{private}", chat_id=int(GROUP), message_id=61, user=self.bruno)
        await handle_callback_query(update, self.context)
        self.assertEqual(query.answer.call_args.args[0], "I posti per questo tavolo sono esauriti!")
        self.assertEqual(db.get_waitlist(private), [])

    async def test_a_failed_dm_is_ignored(self):
        from telegram.error import Forbidden

        async def send(**kwargs):
            if kwargs.get("chat_id") == 2:
                raise Forbidden("bot can't initiate conversation")
        self.context.bot.send_message.side_effect = send
        await self.press(f"full_{self.event_id}", self.bruno)
        await self.press(f"unbook_{self.event_id}", self.anna)
        self.assertEqual(db.get_reservation_by_user(self.event_id, user_id=2)["seats_booked"], 1)


if __name__ == "__main__":
    unittest.main()
