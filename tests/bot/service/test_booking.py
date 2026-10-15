import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import core.db as db
from bot.service.booking import format_conflict_warning_message, handle_seat_booking, handle_seat_unbooking
from tests.support.config import patched_config
from tests.support.db import (
    SUBSCRIBED_EVENT,
    TempDBMixin,
    create_event,
    create_no_username_event,
    create_subscribed_event,
)
from tests.support.telegram import callback_update, make_context, make_user


def _messages(mock_method):
    return [call[0][0] for call in mock_method.call_args_list]


class TestBookingAuditLogging(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.event_id = create_event(
            original_text="Original text", title="Log Test Event", date="10-10-2026", normalized_date="10-10-2026",
            system="D&D", host="GameMaster", seats="1/1", max_seats=1, description="Test description",
        )
        self.user = make_user(112233, "test_player", first_name="Player")
        _update, self.query = callback_update("book", chat_id=9999, message_id=100)
        self.context = make_context()

    async def test_booking_logging_success_and_failure(self):
        with patch("bot.service.booking.logger") as mock_logger, \
             patch("bot.service.booking.update_event_messages", AsyncMock()):
            await handle_seat_booking(self.event_id, self.user, self.query, self.context)
            mock_logger.info.assert_called()
            self.assertTrue(any("112233" in msg and f"#{self.event_id}" in msg and "booked" in msg
                                for msg in _messages(mock_logger.info)))

            user2 = make_user(445566, "another_player", first_name="Player2")
            await handle_seat_booking(self.event_id, user2, self.query, self.context)
            mock_logger.warning.assert_called()
            self.assertTrue(any("445566" in msg and f"#{self.event_id}" in msg and "failed" in msg
                                for msg in _messages(mock_logger.warning)))

    async def test_unbooking_logging_success_and_failure(self):
        with patch("bot.service.booking.update_event_messages", AsyncMock()):
            await handle_seat_booking(self.event_id, self.user, self.query, self.context)

            with patch("bot.service.booking.logger") as mock_logger:
                await handle_seat_unbooking(self.event_id, self.user, self.query, self.context)
                mock_logger.info.assert_called()
                self.assertTrue(any("112233" in msg and f"#{self.event_id}" in msg and "unbooked" in msg
                                    for msg in _messages(mock_logger.info)))

                await handle_seat_unbooking(self.event_id, self.user, self.query, self.context)
                mock_logger.warning.assert_called()
                self.assertTrue(any("112233" in msg and f"#{self.event_id}" in msg and "failed to unbook" in msg
                                    for msg in _messages(mock_logger.warning)))


@contextmanager
def booking_chats():
    """Discussion group / channel config plus a no-op update_event_messages, as in a real booking click."""
    with patched_config(DISCUSSION_GROUP_ID="-100123456", PUBLIC_CHANNEL_ID="-1007890"), \
         patch("bot.service.booking.update_event_messages", AsyncMock()):
        yield


def discussion_query(message_id):
    return callback_update("book", chat_id=-100123456, message_id=message_id)[1]


class TestConflictWarnings(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.event_id = create_subscribed_event()
        self.context = make_context()
        self.send_message = self.context.bot.send_message

    def _same_day_event(self):
        event_id = db.insert_event({**SUBSCRIBED_EVENT, "title": "Call of Cthulhu",
                                    "message_link": "https://t.me/c/123/999"}, None, "raw text")
        db.update_event_status(event_id, "approved")
        return event_id

    def test_format_conflict_warning_message(self):
        user = make_user(username="mario", first_name="Mario")

        ev1 = {"title": "Avventura D&D", "system": "D&D 5e", "message_link": "https://t.me/c/123/456"}
        msg1 = format_conflict_warning_message(user, [ev1])
        self.assertIn("⚠️ <b>Attenzione @mario:</b>", msg1)
        self.assertIn("risulti già iscritto a un altro evento per la stessa data:", msg1)
        self.assertIn('<a href="https://t.me/c/123/456"><b>Avventura D&amp;D</b></a>', msg1)
        self.assertIn("D&amp;D 5e", msg1)
        self.assertIn("La tua prenotazione è stata registrata regolarmente", msg1)
        self.assertIn("liberare il posto", msg1)

        ev2 = {"title": "Call of Cthulhu", "system": "Horror", "message_link": ""}
        msg2 = format_conflict_warning_message(user, [ev1, ev2])
        self.assertIn("⚠️ <b>Attenzione @mario:</b>", msg2)
        self.assertIn("risulti già iscritto ad altri 2 eventi per la stessa data:", msg2)
        self.assertIn('<a href="https://t.me/c/123/456"><b>Avventura D&amp;D</b></a>', msg2)
        self.assertIn("<b>Call of Cthulhu</b>", msg2)

        # User without username (first_name only)
        msg3 = format_conflict_warning_message(make_user(2003, None, first_name="Luigi"), [ev1])
        self.assertIn('<a href="tg://user?id=2003">Luigi</a>', msg3)

    async def test_handle_seat_booking_conflict_warning(self):
        ev2_id = self._same_day_event()
        user = make_user(1001, "mario", first_name="Mario")

        with booking_chats():
            # Mario books ev2 while already booked on the first event
            await handle_seat_booking(ev2_id, user, discussion_query(555), self.context)

            # The reservation succeeds as normal
            res = db.get_reservation_by_user(ev2_id, user_id=1001)
            self.assertIsNotNone(res)
            self.assertEqual(res["seats_booked"], 1)

            # Two messages are sent: the booking confirmation, then the conflict warning
            self.assertEqual(self.send_message.call_count, 2)

            first_call_args = self.send_message.call_args_list[0][1]
            self.assertIn("ha prenotato 1 posto", first_call_args["text"])
            self.assertIn('<a href="https://t.me/c/123/999"><b>Call of Cthulhu</b></a>', first_call_args["text"])
            self.assertNotIn("\nhttps://t.me/c/123/999", first_call_args["text"])
            self.assertEqual(first_call_args["parse_mode"], "HTML")

            second_call_args = self.send_message.call_args_list[1][1]
            self.assertIn("Attenzione @mario", second_call_args["text"])
            self.assertIn("<b>Avventura D&amp;D</b>", second_call_args["text"])
            self.assertIn("La tua prenotazione è stata registrata regolarmente", second_call_args["text"])

    async def test_handle_seat_booking_no_conflict(self):
        # A user with no other bookings
        user = make_user(2002, "peach", first_name="Peach")

        with booking_chats():
            await handle_seat_booking(self.event_id, user, discussion_query(556), self.context)

            # The reservation succeeds as normal
            res = db.get_reservation_by_user(self.event_id, user_id=2002)
            self.assertIsNotNone(res)
            self.assertEqual(res["seats_booked"], 1)

            # Only ONE message (the booking confirmation), NO warning
            self.assertEqual(self.send_message.call_count, 1)
            call_args = self.send_message.call_args[1]
            self.assertIn("ha prenotato 1 posto", call_args["text"])
            self.assertIn("<b>Avventura D&amp;D</b>", call_args["text"])
            self.assertEqual(call_args["parse_mode"], "HTML")
            self.assertNotIn("Attenzione", call_args["text"])

    async def test_handle_seat_unbooking_formatting(self):
        user = make_user(1001, "mario", first_name="Mario")
        ev2_id = self._same_day_event()
        db.book_seat(ev2_id, 1001, "mario")

        with booking_chats():
            await handle_seat_unbooking(ev2_id, user, discussion_query(777), self.context)

            self.assertIsNone(db.get_reservation_by_user(ev2_id, user_id=1001))

            self.send_message.assert_called_once()
            call_args = self.send_message.call_args[1]
            self.assertIn("ha liberato 1 posto", call_args["text"])
            self.assertIn('<a href="https://t.me/c/123/999"><b>Call of Cthulhu</b></a>', call_args["text"])
            self.assertNotIn("\nhttps://t.me/c/123/999", call_args["text"])
            self.assertEqual(call_args["parse_mode"], "HTML")


class TestSubscribersWithoutUsername(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_handle_seat_booking_for_user_without_username(self):
        event_id = create_no_username_event()
        user = make_user(8893283822, None, first_name="Lorenzo", full_name="Lorenzo Duarte")
        user.last_name = "Duarte"
        query = discussion_query(111)
        context = make_context()

        with booking_chats():
            await handle_seat_booking(event_id, user, query, context)

            res = db.get_reservation_by_user(event_id, user_id=8893283822)
            self.assertIsNotNone(res)
            self.assertIsNone(res["username"])
            self.assertEqual(res["full_name"], "Lorenzo Duarte")
            self.assertEqual(res["seats_booked"], 1)

            context.bot.send_message.assert_called()
            sent_text = context.bot.send_message.call_args[1]["text"]
            self.assertNotIn("@Lorenzo", sent_text)
            self.assertIn('<a href="tg://user?id=8893283822">Lorenzo Duarte</a>', sent_text)

            await handle_seat_unbooking(event_id, user, query, context)
            self.assertIsNone(db.get_reservation_by_user(event_id, user_id=8893283822))


if __name__ == "__main__":
    unittest.main()
