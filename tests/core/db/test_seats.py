import unittest

import core.db as db
from tests.support.db import TempDBMixin, create_subscribed_event


class TestSeatBookkeeping(TempDBMixin, unittest.TestCase):
    def test_partial_and_full_subscriber_removal_keep_counters_in_sync(self):
        event_id = db.insert_event({"title": "T", "max_seats": 5, "seats": "5/5"}, None, "raw")
        self.assertTrue(db.admin_add_subscriber(event_id, "@mario", seats=3)[0])
        self.assertEqual(db.get_event(event_id)["seats"], "2/5")

        ok, msg = db.admin_remove_subscriber(event_id, "mario", seats=1)
        self.assertTrue(ok)
        self.assertIn("Rimossi 1", msg)
        self.assertEqual(db.get_event(event_id)["booked_seats"], 2)

        db.admin_remove_subscriber(event_id, "mario")
        self.assertEqual(db.get_event(event_id)["seats"], "5/5")
        self.assertEqual(db.get_reservations_for_event(event_id), [])

    def test_capacity_and_cancelled_checks(self):
        event_id = db.insert_event({"title": "T", "max_seats": 1}, None, "raw")
        self.assertTrue(db.book_seat(event_id, 1, username="a")[0])
        self.assertEqual(db.book_seat(event_id, 2, username="b"), (False, "Nessun posto disponibile."))
        db.update_event_status(event_id, "cancelled")
        self.assertEqual(db.unbook_seat(event_id, 1), (False, "Evento annullato."))
        self.assertEqual(db.book_seat(999, 1), (False, "Evento non trovato."))

    def test_status_queries_use_string_literals(self):
        event_id = db.insert_event({"title": "T", "normalized_date": "07-10-2026"}, None, "raw")
        db.update_event_status(event_id, "approved")
        self.assertEqual([e["id"] for e in db.get_pending_events_for_recap("07-10-2026")], [event_id])
        self.assertEqual([e["id"] for e in db.get_approved_events_for_date("07/10/2026")], [event_id])


class TestAdminSubscribers(TempDBMixin, unittest.TestCase):
    def test_db_admin_subscribers(self):
        event_id = create_subscribed_event()
        subs = db.get_reservations_for_event(event_id)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["username"], "mario")
        self.assertEqual(subs[0]["seats_booked"], 1)

        # Admin adds new subscriber @luigi with 2 seats
        ok, msg = db.admin_add_subscriber(event_id, "@luigi", seats=2)
        self.assertTrue(ok)
        subs = db.get_reservations_for_event(event_id)
        self.assertEqual(len(subs), 2)
        luigi = next(s for s in subs if s["username"] == "luigi")
        self.assertEqual(luigi["seats_booked"], 2)

        ev = db.get_event(event_id)
        self.assertEqual(ev["booked_seats"], 4)
        self.assertEqual(ev["seats"], "1/5")

        # Admin adds 1 seat to luigi
        ok, msg = db.admin_add_seat(event_id, luigi["id"])
        self.assertTrue(ok)
        ev = db.get_event(event_id)
        self.assertEqual(ev["booked_seats"], 5)
        self.assertEqual(ev["seats"], "0/5")

        # Admin tries to add another seat beyond max_seats (5) -> should fail
        ok, msg = db.admin_add_seat(event_id, luigi["id"])
        self.assertFalse(ok)
        self.assertIn("raggiunta", msg.lower())

        # Admin tries to add subscriber beyond max_seats -> should fail
        ok, msg = db.admin_add_subscriber(event_id, "toad", seats=1)
        self.assertFalse(ok)
        self.assertIn("superata", msg.lower())

        # Admin removes 1 seat from luigi
        ok, msg = db.admin_remove_seat(event_id, luigi["id"])
        self.assertTrue(ok)
        luigi = next(s for s in db.get_reservations_for_event(event_id) if s["username"] == "luigi")
        self.assertEqual(luigi["seats_booked"], 2)

        # Admin removes subscriber luigi completely
        ok, msg = db.admin_remove_subscriber(event_id, "luigi")
        self.assertTrue(ok)
        self.assertEqual(len(db.get_reservations_for_event(event_id)), 1)


class TestEventbriteSeats(TempDBMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.event_id = db.insert_event({"title": "T", "max_seats": 4, "seats": "4/4"}, None, "raw")
        db.update_event_status(self.event_id, "approved")

    def test_new_order_adds_row_and_updates_counters(self):
        self.assertEqual(db.apply_eventbrite_order(self.event_id, "o1", "Mario R.", 2), (0, 2, False))
        row = db.get_eventbrite_reservations(self.event_id)[0]
        self.assertEqual((row["full_name"], row["seats_booked"], row["source"], row["eventbrite_order_id"]),
                         ("Mario R.", 2, "eventbrite", "o1"))
        self.assertIsNone(row["user_id"])
        self.assertIsNone(row["username"])
        ev = db.get_event(self.event_id)
        self.assertEqual((ev["booked_seats"], ev["seats"]), (2, "2/4"))
        self.assertEqual(db.eventbrite_seat_count(self.event_id), 2)

    def test_increase_decrease_and_delete(self):
        db.apply_eventbrite_order(self.event_id, "o1", "Mario R.", 1)
        self.assertEqual(db.apply_eventbrite_order(self.event_id, "o1", "Mario R.", 3), (1, 3, False))
        self.assertEqual(db.get_event(self.event_id)["booked_seats"], 3)
        self.assertEqual(db.apply_eventbrite_order(self.event_id, "o1", "Mario R.", 2), (3, 2, False))
        self.assertEqual(db.apply_eventbrite_order(self.event_id, "o1", "Mario R.", 0), (2, 0, False))
        self.assertEqual(db.get_eventbrite_reservations(self.event_id), [])
        ev = db.get_event(self.event_id)
        self.assertEqual((ev["booked_seats"], ev["seats"]), (0, "4/4"))

    def test_zero_seats_for_unknown_order_is_a_no_op(self):
        self.assertEqual(db.apply_eventbrite_order(self.event_id, "ghost", "X", 0), (0, 0, False))
        self.assertEqual(db.get_event(self.event_id)["booked_seats"], 0)

    def test_overbooking_is_applied_and_flagged(self):
        db.book_seat(self.event_id, 1, username="a")
        db.book_seat(self.event_id, 2, username="b")
        db.book_seat(self.event_id, 3, username="c")
        self.assertEqual(db.apply_eventbrite_order(self.event_id, "o1", "Mario R.", 3), (0, 3, True))
        ev = db.get_event(self.event_id)
        self.assertEqual((ev["booked_seats"], ev["seats"]), (6, "0/4"))

    def test_unlimited_event_is_never_overbooked(self):
        event_id = db.insert_event({"title": "U", "max_seats": None}, None, "raw")
        self.assertEqual(db.apply_eventbrite_order(event_id, "o1", "Mario R.", 9), (0, 9, False))

    def test_cancelled_event_still_tracks_orders(self):
        db.update_event_status(self.event_id, "cancelled")
        self.assertEqual(db.apply_eventbrite_order(self.event_id, "o1", "Mario R.", 1), (0, 1, False))

    def test_missing_event_returns_none(self):
        self.assertIsNone(db.apply_eventbrite_order(999, "o1", "Mario R.", 1))

    def test_unique_index_blocks_duplicate_order_rows(self):
        db.apply_eventbrite_order(self.event_id, "o1", "Mario R.", 1)
        db.apply_eventbrite_order(self.event_id, "o1", "Mario R.", 2)
        self.assertEqual(len(db.get_eventbrite_reservations(self.event_id)), 1)

    def test_admin_seat_changes_are_refused_on_eventbrite_rows(self):
        db.apply_eventbrite_order(self.event_id, "o1", "Mario R.", 2)
        res_id = db.get_eventbrite_reservations(self.event_id)[0]["id"]
        expected = (False, "Prenotazione Eventbrite: gestiscila dalla dashboard Eventbrite.")
        self.assertEqual(db.admin_add_seat(self.event_id, res_id), expected)
        self.assertEqual(db.admin_remove_seat(self.event_id, res_id), expected)
        self.assertEqual(db.get_event(self.event_id)["booked_seats"], 2)

    def test_telegram_flows_never_match_eventbrite_rows(self):
        db.apply_eventbrite_order(self.event_id, "o1", "Mario R.", 2)
        # A Telegram user whose display name equals the Eventbrite name
        self.assertEqual(db.unbook_seat(self.event_id, 77, username="Mario R."),
                         (False, "Non hai posti prenotati da liberare."))
        self.assertEqual(db.admin_remove_subscriber(self.event_id, "Mario R.")[0], False)
        self.assertEqual(db.get_event(self.event_id)["booked_seats"], 2)

        self.assertTrue(db.book_seat(self.event_id, 77, username=None, full_name="Mario R.")[0])
        self.assertTrue(db.admin_add_subscriber(self.event_id, "Mario R.", seats=1)[0])
        self.assertEqual(db.eventbrite_seat_count(self.event_id), 2)
        self.assertEqual(sum(r["seats_booked"] for r in db.get_reservations_for_event(self.event_id)), 4)
        self.assertIsNone(db.get_reservation_by_user(self.event_id, username="nobody"))


if __name__ == "__main__":
    unittest.main()
