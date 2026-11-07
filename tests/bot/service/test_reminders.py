import unittest
from datetime import datetime
from unittest.mock import patch

from telegram.error import Forbidden

import core.db as db
from bot.service.reminders import send_event_reminders
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import make_bot

TODAY = datetime(2026, 11, 7, 12, 0)


@patch("bot.service.reminders.SEND_INTERVAL", 0)
class TestEventReminders(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.today = create_event(status="approved", title="Stasera", date="07-11-2026 21:00",
                                  normalized_date="07-11-2026", max_seats=5, seats="5/5")
        db.book_seat(self.today, 1, username="anna")
        db.book_seat(self.today, 1, username="anna")
        db.book_seat(self.today, 2, username="bruno")
        db.admin_add_subscriber(self.today, "nouserid")  # added by an admin: no user_id, no DM possible
        tomorrow = create_event(status="approved", normalized_date="08-11-2026", max_seats=5, seats="5/5")
        db.book_seat(tomorrow, 3, username="carla")
        cancelled = create_event(normalized_date="07-11-2026", max_seats=5, seats="5/5")
        db.update_event_status(cancelled, "approved")
        db.book_seat(cancelled, 4, username="dario")
        db.update_event_status(cancelled, "cancelled")

    async def test_only_todays_approved_events_and_reachable_users(self):
        bot = make_bot()
        sent = await send_event_reminders(bot, today=TODAY)
        self.assertEqual(sent, 2)
        by_user = {call.kwargs["chat_id"]: call.kwargs for call in bot.send_message.call_args_list}
        self.assertEqual(set(by_user), {1, 2})
        self.assertIn("Hai prenotato 2 posti", by_user[1]["text"])
        buttons = by_user[2]["reply_markup"].inline_keyboard[0]
        self.assertEqual(buttons[0].callback_data, f"dmunbook_{self.today}")
        self.assertIn("20261107T210000", buttons[1].url)

    async def test_users_who_never_opened_the_bot_are_skipped(self):
        bot = make_bot()

        async def send(**kwargs):
            if kwargs["chat_id"] == 1:
                raise Forbidden("bot can't initiate conversation with a user")
        bot.send_message.side_effect = send
        self.assertEqual(await send_event_reminders(bot, today=TODAY), 1)


if __name__ == "__main__":
    unittest.main()
