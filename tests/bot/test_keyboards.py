import unittest

import core.db as db
from bot.keyboards import (
    get_approval_keyboard,
    get_approved_event_keyboard,
    get_cancelled_event_keyboard,
    get_event_booking_keyboard,
    get_schedule_repost_keyboard,
    get_subscribers_management_keyboard,
)
from tests.support.config import patched_config
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


if __name__ == "__main__":
    unittest.main()
