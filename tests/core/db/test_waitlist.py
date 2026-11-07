import unittest

import core.db as db
from tests.support.db import TempDBMixin, create_event


class TestWaitlist(TempDBMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.event_id = create_event(status="approved", seats="0/1", max_seats=1, booked_seats=0)
        self.assertTrue(db.book_seat(self.event_id, 1, username="anna")[0])

    def test_positions_and_no_duplicates(self):
        self.assertEqual(db.join_waitlist(self.event_id, 2, username="bruno"), (1, True))
        self.assertEqual(db.join_waitlist(self.event_id, 3, full_name="Carla Rossi"), (2, True))
        self.assertEqual(db.join_waitlist(self.event_id, 2, username="bruno"), (1, False))
        self.assertEqual(db.waitlist_count(self.event_id), 2)
        self.assertEqual(db.get_event(self.event_id)["waitlist_count"], 2)
        self.assertTrue(db.leave_waitlist(self.event_id, 2))
        self.assertEqual(db.waitlist_position(self.event_id, 3), 1)
        self.assertFalse(db.leave_waitlist(self.event_id, 2))

    def test_unlimited_or_cancelled_events_have_no_waitlist(self):
        unlimited = create_event(status="approved", max_seats=None)
        cancelled = create_event(status="cancelled", max_seats=1)
        self.assertEqual(db.join_waitlist(unlimited, 2), (None, False))
        self.assertEqual(db.join_waitlist(cancelled, 2), (None, False))

    def test_promotion_fills_the_free_seats_in_order(self):
        db.join_waitlist(self.event_id, 2, username="bruno")
        db.join_waitlist(self.event_id, 3, username="carla")
        self.assertEqual(db.promote_waitlist(self.event_id), [])  # still full
        db.unbook_seat(self.event_id, 1)
        promoted = db.promote_waitlist(self.event_id)
        self.assertEqual([p["user_id"] for p in promoted], [2])
        event = db.get_event(self.event_id)
        self.assertEqual((event["booked_seats"], event["seats"], event["waitlist_count"]), (1, "0/1", 1))
        self.assertEqual(db.get_reservation_by_user(self.event_id, user_id=2)["seats_booked"], 1)

    def test_more_capacity_promotes_several(self):
        for user_id in (2, 3, 4):
            db.join_waitlist(self.event_id, user_id)
        db.update_event_field(self.event_id, "max_seats", 3)
        self.assertEqual([p["user_id"] for p in db.promote_waitlist(self.event_id)], [2, 3])
        self.assertEqual(db.waitlist_count(self.event_id), 1)

    def test_no_promotion_on_a_cancelled_event(self):
        db.join_waitlist(self.event_id, 2)
        db.unbook_seat(self.event_id, 1)
        db.update_event_status(self.event_id, "cancelled")
        self.assertEqual(db.promote_waitlist(self.event_id), [])
        self.assertEqual(db.waitlist_count(self.event_id), 1)

    def test_a_seat_holder_can_queue_for_one_more(self):
        self.assertEqual(db.join_waitlist(self.event_id, 1, username="anna"), (1, True))

    def test_delete_and_clear(self):
        db.join_waitlist(self.event_id, 2)
        self.assertEqual(db.clear_waitlist(self.event_id), 1)
        db.join_waitlist(self.event_id, 2)
        db.delete_event(self.event_id)
        self.assertEqual(db.get_waitlist(self.event_id), [])


if __name__ == "__main__":
    unittest.main()
