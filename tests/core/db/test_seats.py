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


if __name__ == "__main__":
    unittest.main()
