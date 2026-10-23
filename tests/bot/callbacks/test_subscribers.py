import unittest
from unittest.mock import AsyncMock, patch

import core.db as db
from bot.callbacks.router import handle_callback_query
from bot.callbacks.subscribers import format_subscribers_management_view
from tests.support.config import patched_config
from tests.support.db import (
    SUBSCRIBED_EVENT,
    TempDBMixin,
    create_no_username_event,
    create_subscribed_event,
    create_unpublished_event,
)
from tests.support.telegram import callback_update, make_context, make_user

MANAGEMENT_VIEW_TEXT = "👥 Gestione Iscritti\n📌 Avventura D&D"


class TestSubscribersManagementView(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.event_id = create_subscribed_event()
        self.context = make_context()

    def test_subscribers_management_view_bold_title(self):
        reservations = [{"username": "mario", "seats_booked": 1}]
        ev = {**SUBSCRIBED_EVENT, "id": self.event_id, "message_link": "https://t.me/c/123/456"}
        view = format_subscribers_management_view(ev, reservations)
        self.assertIn('📌 <a href="https://t.me/c/123/456"><b>Avventura D&amp;D</b></a>', view)

        ev_no_link = {**SUBSCRIBED_EVENT, "id": self.event_id, "message_link": None}
        view_no_link = format_subscribers_management_view(ev_no_link, reservations)
        self.assertIn('📌 <b>Avventura D&amp;D</b>', view_no_link)

    async def test_manage_subs_callbacks(self):
        update, query = callback_update(f"manage_subs_{self.event_id}", chat_id=999, message_id=123, text="Post text")
        send_message = self.context.bot.send_message

        # 1. Open the management view from the event message
        await handle_callback_query(update, self.context)
        send_message.assert_called_once()
        msg_call = send_message.call_args[1]
        self.assertIn("Gestione Iscritti", msg_call["text"])
        self.assertEqual(msg_call["reply_to_message_id"], 123)

        # 2. Refresh the view when pressed on the management message
        query.message.text = MANAGEMENT_VIEW_TEXT
        await handle_callback_query(update, self.context)
        query.edit_message_text.assert_called_once()

        # 3. sub_inc_
        res_id = db.get_reservations_for_event(self.event_id)[0]["id"]
        query.data = f"sub_inc_{self.event_id}_{res_id}"
        query.edit_message_text.reset_mock()
        with patch("bot.callbacks.subscribers.update_event_messages", AsyncMock()):
            await handle_callback_query(update, self.context)
            query.edit_message_text.assert_called_once()
            self.assertEqual(db.get_reservations_for_event(self.event_id)[0]["seats_booked"], 2)

        # 4. sub_dec_
        query.data = f"sub_dec_{self.event_id}_{res_id}"
        query.edit_message_text.reset_mock()
        with patch("bot.callbacks.subscribers.update_event_messages", AsyncMock()):
            await handle_callback_query(update, self.context)
            query.edit_message_text.assert_called_once()
            self.assertEqual(db.get_reservations_for_event(self.event_id)[0]["seats_booked"], 1)

        # 5. sub_addnew_
        query.data = f"sub_addnew_{self.event_id}"
        send_message.reset_mock()
        await handle_callback_query(update, self.context)
        send_message.assert_called_once()
        self.assertIn("Invia l'username Telegram, rispondendo a questo messaggio, da aggiungere",
                      send_message.call_args[1]["text"])

        # 6. close_subs_
        query.data = f"close_subs_{self.event_id}"
        await handle_callback_query(update, self.context)
        query.message.delete.assert_called_once()

    async def test_admin_action_notice_on_callback_queries(self):
        res_id = db.get_reservations_for_event(self.event_id)[0]["id"]
        update, query = callback_update(f"sub_inc_{self.event_id}_{res_id}", chat_id=999, message_id=123,
                                        text=MANAGEMENT_VIEW_TEXT, user=make_user(username="table_master"))
        send_message = self.context.bot.send_message

        with patched_config(DISCUSSION_GROUP_ID="-100123456"), \
             patch("bot.callbacks.subscribers.update_event_messages", AsyncMock()):
            # sub_inc_
            await handle_callback_query(update, self.context)
            send_message.assert_called_once()
            call_kwargs = send_message.call_args[1]
            self.assertEqual(call_kwargs["chat_id"], -100123456)
            self.assertIn("admin degli eventi", call_kwargs["text"].lower())
            self.assertIn("@mario", call_kwargs["text"])
            self.assertIn("Aggiunto 1 posto", call_kwargs["text"])

            # sub_dec_
            send_message.reset_mock()
            query.data = f"sub_dec_{self.event_id}_{res_id}"
            await handle_callback_query(update, self.context)
            send_message.assert_called_once()
            call_kwargs = send_message.call_args[1]
            self.assertEqual(call_kwargs["chat_id"], -100123456)
            self.assertIn("admin degli eventi", call_kwargs["text"].lower())
            self.assertIn("@mario", call_kwargs["text"])
            self.assertIn("Rimosso 1 posto", call_kwargs["text"])


class TestSubscribersWithoutUsername(TempDBMixin, unittest.TestCase):
    def test_format_subscribers_management_view_no_at_for_non_username(self):
        event = db.get_event(create_no_username_event())
        reservations = [
            {"username": None, "user_id": 8893283822, "full_name": "Lorenzo Duarte", "seats_booked": 1},
        ]
        view = format_subscribers_management_view(event, reservations)
        self.assertNotIn("@Lorenzo", view)
        self.assertIn('<b><a href="tg://user?id=8893283822">Lorenzo Duarte</a></b> — 1 posto', view)


class TestUnpublishedEventSubscribers(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.pending_event_id = create_unpublished_event()
        self.assertEqual(db.get_event(self.pending_event_id)["status"], "pending")

    async def test_unpublished_event_sub_inc_and_dec_callbacks_do_not_send_discussion_notice(self):
        db.admin_add_subscriber(self.pending_event_id, "@player1", seats=1)
        res_id = db.get_reservations_for_event(self.pending_event_id)[0]["id"]
        update, query = callback_update(f"sub_inc_{self.pending_event_id}_{res_id}", chat_id=999,
                                        text="👥 Gestione Iscritti", user=make_user(111, "chief_admin"))
        context = make_context()

        with patched_config(DISCUSSION_GROUP_ID="-100123456"), \
             patch("bot.callbacks.subscribers.update_event_messages", AsyncMock()):
            # sub_inc_
            await handle_callback_query(update, context)

            self.assertEqual(db.get_reservations_for_event(self.pending_event_id)[0]["seats_booked"], 2)
            context.bot.send_message.assert_not_called()

            # sub_dec_
            query.data = f"sub_dec_{self.pending_event_id}_{res_id}"
            await handle_callback_query(update, context)

            self.assertEqual(db.get_reservations_for_event(self.pending_event_id)[0]["seats_booked"], 1)
            context.bot.send_message.assert_not_called()


class TestEventbriteInManagementView(unittest.TestCase):
    def test_legend_only_appears_with_eventbrite_bookings(self):
        event = {**SUBSCRIBED_EVENT, "id": 1, "message_link": None}
        telegram_only = [{"username": "mario", "seats_booked": 1, "source": "telegram"}]
        mixed = telegram_only + [{"full_name": "Anna B.", "seats_booked": 2, "source": "eventbrite"}]
        self.assertNotIn("Eventbrite", format_subscribers_management_view(event, telegram_only))
        view = format_subscribers_management_view(event, mixed)
        self.assertIn("🎟️ = prenotazione Eventbrite (gestisci dalla dashboard)", view)
        self.assertIn("1. <b>@mario</b>", view)
        self.assertIn("2. <b>🎟️ Anna B.</b> — 2 posti", view)


class TestEventbriteSeatButtons(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_stale_seat_buttons_on_eventbrite_rows_are_refused(self):
        event_id = create_subscribed_event()
        db.apply_eventbrite_order(event_id, "o1", "Mario R.", 2)
        res_id = db.get_eventbrite_reservations(event_id)[0]["id"]
        expected = "Prenotazione Eventbrite: gestiscila dalla dashboard Eventbrite."

        for action in ("sub_inc", "sub_dec"):
            update, query = callback_update(f"{action}_{event_id}_{res_id}", chat_id=999)
            with patch("bot.callbacks.subscribers.update_event_messages", AsyncMock()) as update_messages:
                await handle_callback_query(update, make_context())
            query.answer.assert_awaited_with(expected, show_alert=True)
            update_messages.assert_not_awaited()

        self.assertEqual(db.eventbrite_seat_count(event_id), 2)
        self.assertEqual(db.get_event(event_id)["booked_seats"], 4)


if __name__ == "__main__":
    unittest.main()
