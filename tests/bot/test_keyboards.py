import unittest

import core.db as db
from bot.keyboards import (
    get_approval_keyboard,
    get_approved_event_keyboard,
    get_cancel_confirmation_keyboard,
    get_cancelled_event_keyboard,
    get_event_booking_keyboard,
    get_schedule_repost_keyboard,
    get_subscribers_management_keyboard,
)
from tests.support.config import eventbrite_credentials, patched_config
from tests.support.db import TempDBMixin, create_deep_link_event, create_no_username_event, create_subscribed_event


def callbacks(keyboard):
    return [btn.callback_data for row in keyboard.inline_keyboard for btn in row]


class TestScheduleKeyboard(unittest.TestCase):
    def test_active_days_checked_by_key_or_name(self):
        rows = get_schedule_repost_keyboard(3, ["Lunedì", "ven"]).inline_keyboard
        labels = [b.text for b in rows[0] + rows[1]]
        self.assertEqual(labels, ["✅ Lunedì", "⬜ Mercoledì", "✅ Venerdì", "⬜ Sabato", "⬜ Domenica"])
        self.assertEqual(rows[0][0].callback_data, "sched_toggle_3_lun")


class TestEventKeyboards(TempDBMixin, unittest.TestCase):
    def test_keyboards_structure(self):
        # The classic layout, i.e. what the bot shows while Eventbrite is not configured
        config_patch = patched_config(EVENTBRITE_TOKEN=None, EVENTBRITE_ORGANIZATION_ID=None, EVENTBRITE_VENUE_ID=None)
        config_patch.__enter__()
        self.addCleanup(config_patch.__exit__, None, None, None)
        event_id = create_subscribed_event()

        appr_kb = get_approval_keyboard(event_id)
        self.assertEqual(len(appr_kb.inline_keyboard), 2)
        self.assertEqual(appr_kb.inline_keyboard[1][0].callback_data, f"manage_subs_{event_id}")
        appr_callbacks = callbacks(appr_kb)
        self.assertIn(f"publish_event_{event_id}", appr_callbacks)
        self.assertIn(f"discard_event_{event_id}", appr_callbacks)
        self.assertNotIn(f"cancel_event_{event_id}", appr_callbacks)

        approved_kb = get_approved_event_keyboard(event_id)
        self.assertEqual(approved_kb.inline_keyboard[0][0].callback_data, f"cancel_event_{event_id}")
        self.assertEqual(approved_kb.inline_keyboard[0][1].callback_data, f"manage_subs_{event_id}")

        cancelled_kb = get_cancelled_event_keyboard(event_id)
        self.assertEqual(cancelled_kb.inline_keyboard[0][0].callback_data, f"reactivate_event_{event_id}")
        self.assertEqual(cancelled_kb.inline_keyboard[0][1].callback_data, f"manage_subs_{event_id}")

        subs_kb = get_subscribers_management_keyboard(event_id, db.get_reservations_for_event(event_id))
        self.assertTrue(any("sub_inc_" in data for data in callbacks(subs_kb)))
        self.assertTrue(any("sub_dec_" in data for data in callbacks(subs_kb)))

    def test_get_subscribers_management_keyboard_no_at_for_non_username(self):
        event_id = create_no_username_event()
        reservations = [
            {"id": 1, "username": None, "user_id": 8893283822, "full_name": "Lorenzo Duarte", "seats_booked": 1},
        ]
        kb = get_subscribers_management_keyboard(event_id, reservations)
        btn_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        for t in btn_texts:
            self.assertNotIn("@Lorenzo", t)
        self.assertTrue(any("Lorenzo Dua…" in t for t in btn_texts))


class TestBookingKeyboard(TempDBMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.event_id = create_deep_link_event()

    def test_booking_keyboard_without_bot_username(self):
        with patched_config(TELEGRAM_BOT_USERNAME=None):
            kb = get_event_booking_keyboard(self.event_id)
            self.assertEqual(len(kb.inline_keyboard), 1)
            row = kb.inline_keyboard[0]
            self.assertEqual(len(row), 2)
            self.assertEqual(row[0].text, "➕ Prenota")
            self.assertEqual(row[0].callback_data, f"book_{self.event_id}")
            self.assertEqual(row[1].text, "➖ Annulla")
            self.assertEqual(row[1].callback_data, f"unbook_{self.event_id}")

    def test_booking_keyboard_with_bot_username(self):
        kb = get_event_booking_keyboard(self.event_id, bot_username="GdG_Event_bot")
        self.assertEqual(len(kb.inline_keyboard), 1)
        row = kb.inline_keyboard[0]
        self.assertEqual(len(row), 3)
        self.assertEqual(row[0].text, "➕ Prenota")
        self.assertEqual(row[0].callback_data, f"book_{self.event_id}")
        self.assertEqual(row[1].text, "👥 Lista")
        self.assertEqual(row[1].url, f"https://t.me/GdG_Event_bot?start=subs_{self.event_id}")
        self.assertEqual(row[2].text, "➖ Annulla")
        self.assertEqual(row[2].callback_data, f"unbook_{self.event_id}")

    def test_booking_keyboard_with_at_prefix_bot_username(self):
        row = get_event_booking_keyboard(self.event_id, bot_username="@GdG_Event_bot").inline_keyboard[0]
        self.assertEqual(row[1].url, f"https://t.me/GdG_Event_bot?start=subs_{self.event_id}")

    def test_booking_keyboard_when_full(self):
        event = db.get_event(self.event_id)
        event["booked_seats"] = 4
        event["max_seats"] = 4

        row = get_event_booking_keyboard(self.event_id, event=event, bot_username="GdG_Event_bot").inline_keyboard[0]
        self.assertEqual(len(row), 3)
        self.assertEqual(row[0].text, "🚫 Esauriti")
        self.assertEqual(row[0].callback_data, f"full_{self.event_id}")
        self.assertEqual(row[1].text, "👥 Lista")
        self.assertEqual(row[2].text, "➖ Annulla")


EB_EVENT = {"eventbrite_event_id": "eb1"}


class TestEventbriteKeyboards(unittest.TestCase):
    def rows(self, keyboard):
        return [[(b.text, b.callback_data, b.url) for b in row] for row in keyboard.inline_keyboard]

    def test_unconfigured_keyboards_are_exactly_as_before(self):
        with patched_config(EVENTBRITE_TOKEN=None, EVENTBRITE_ORGANIZATION_ID=None, EVENTBRITE_VENUE_ID=None):
            self.assertEqual(len(get_approval_keyboard(5).inline_keyboard), 2)
            self.assertEqual(len(get_approved_event_keyboard(5).inline_keyboard), 1)
            self.assertEqual(len(get_approved_event_keyboard(5, EB_EVENT).inline_keyboard), 1)

    def test_pending_card_offers_publish_plus_eventbrite(self):
        with eventbrite_credentials():
            rows = self.rows(get_approval_keyboard(5))
        self.assertEqual(rows[1], [("🚀 Publish + Eventbrite", "publish_eb_event_5", None)])
        self.assertEqual(rows[2][0][1], "manage_subs_5")

    def test_approved_card_offers_to_publish_until_the_event_is_linked(self):
        with eventbrite_credentials():
            self.assertEqual(self.rows(get_approved_event_keyboard(5))[1],
                             [("🎟️ Pubblica su Eventbrite", "eb_publish_5", None)])
            self.assertEqual(self.rows(get_approved_event_keyboard(5, {"eventbrite_event_id": None}))[1],
                             [("🎟️ Pubblica su Eventbrite", "eb_publish_5", None)])
            self.assertEqual(self.rows(get_approved_event_keyboard(5, EB_EVENT))[1],
                             [("🎟️ Eventbrite", None, "https://www.eventbrite.com/events/eb1/dashboard/?eid=eb1")])

    def test_second_row_offers_the_eventbrite_only_action_for_the_current_state(self):
        dashboard = ("🎟️ Eventbrite", None, "https://www.eventbrite.com/events/eb1/dashboard/?eid=eb1")
        cases = {
            "live": ("🚫 Annulla su Eventbrite", "eb_cancel_ask_5", None),
            "unpublished": ("🚫 Annulla su Eventbrite", "eb_cancel_ask_5", None),
            "closed": ("🔁 Completa annullamento", "eb_cancel_retry_5", None),
            "canceled": ("🎟️ Ricrea su Eventbrite", "eb_recreate_5", None),
        }
        with eventbrite_credentials():
            for status, action in cases.items():
                with self.subTest(status=status):
                    event = {"eventbrite_event_id": "eb1", "eventbrite_status": status}
                    rows = self.rows(get_approved_event_keyboard(5, event))
                    self.assertEqual(rows[1], [dashboard, action])
                    self.assertEqual(rows[0][0][1], "cancel_event_5")  # the Telegram cancel stays on row one
            draft = {"eventbrite_event_id": "eb1", "eventbrite_status": "draft"}
            self.assertEqual(self.rows(get_approved_event_keyboard(5, draft))[1], [dashboard])

    def test_eventbrite_rows_become_a_single_button_opening_their_order(self):
        reservations = [
            {"id": 1, "username": "mario", "user_id": 7, "seats_booked": 1, "source": "telegram"},
            {"id": 2, "username": None, "user_id": None, "full_name": "Mario R.", "seats_booked": 2, "source": "eventbrite",
             "eventbrite_order_id": "111"},
            {"id": 3, "username": None, "user_id": None, "full_name": "Alessandro Montanari", "seats_booked": 1,
             "source": "eventbrite", "eventbrite_order_id": "222"},
        ]
        rows = self.rows(get_subscribers_management_keyboard(5, reservations, event=EB_EVENT))
        self.assertEqual([b[1] for b in rows[0]], ["sub_dec_5_1", "sub_inc_5_1"])
        self.assertEqual(rows[1], [("🎟️ Mario R. (2)", None, "https://www.eventbrite.com/organizations/orders/111")])
        self.assertEqual(rows[2], [("🎟️ Alessandro … (1)", None, "https://www.eventbrite.com/organizations/orders/222")])
        flat = [b for row in rows for b in row]
        self.assertFalse(any(b[1] and b[1].startswith(("sub_inc_5_2", "sub_dec_5_2", "sub_inc_5_3")) for b in flat))
        self.assertEqual(rows[-2][0][1], "sub_addnew_5")

    def test_eventbrite_rows_without_an_order_id_get_no_buttons(self):
        reservations = [{"id": 2, "full_name": "Mario R.", "seats_booked": 2, "source": "eventbrite"}]
        rows = self.rows(get_subscribers_management_keyboard(5, reservations))
        self.assertEqual(len(rows), 2)  # only "Aggiungi" and "Aggiorna/Chiudi"

class TestCancelConfirmationKeyboard(TempDBMixin, unittest.TestCase):
    def rows(self, event_id):
        return [[(b.text, b.callback_data) for b in row] for row in get_cancel_confirmation_keyboard(event_id).inline_keyboard]

    def test_plain_event(self):
        event_id = create_subscribed_event()
        self.assertEqual(self.rows(event_id), [[("✅ Sì, annulla", f"cancel_confirm_{event_id}"),
                                                ("↩️ Indietro", f"cancel_abort_{event_id}")]])

    def test_same_label_with_eventbrite_bookings(self):
        event_id = create_subscribed_event()
        db.apply_eventbrite_order(event_id, "o1", "Mario R.", 1)
        self.assertEqual(self.rows(event_id)[0][0], ("✅ Sì, annulla", f"cancel_confirm_{event_id}"))


if __name__ == "__main__":
    unittest.main()
