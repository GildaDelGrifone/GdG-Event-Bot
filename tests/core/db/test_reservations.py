import unittest
from datetime import date, timedelta

import core.db as db
from core.db.reservations import normalize_identity
from tests.support.db import SUBSCRIBED_EVENT, TempDBMixin, create_event, create_subscribed_event


class TestNormalizeIdentity(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(normalize_identity("@mario", None), ("mario", None))
        self.assertEqual(normalize_identity("Mario Rossi", None), (None, "Mario Rossi"))
        self.assertEqual(normalize_identity("@", "  "), (None, None))
        self.assertEqual(normalize_identity(None, " Anna "), (None, "Anna"))


class TestConflictingEvents(TempDBMixin, unittest.TestCase):
    def _event(self, status="approved", **overrides):
        event_id = db.insert_event({**SUBSCRIBED_EVENT, **overrides}, None, "raw text")
        db.update_event_status(event_id, status)
        return event_id

    def test_get_user_conflicting_events(self):
        # The first event is on "2026-09-05" and mario (1001) is booked on it
        event_id = create_subscribed_event()

        # Event 2: same day, approved
        ev2_id = self._event(title="Call of Cthulhu")

        # Event 3: different day ("2026-09-06"), approved
        ev3_id = self._event(title="Cyberpunk RED", normalized_date="2026-09-06")
        db.book_seat(ev3_id, 1001, "mario")

        # Event 4: same day, but cancelled
        ev4_id = self._event(status="cancelled", title="Vampire V5")
        db.book_seat(ev4_id, 1001, "mario")

        # Event 5: same day, approved, but the user unsubscribed
        ev5_id = self._event(title="Pathfinder 2e")
        db.book_seat(ev5_id, 1001, "mario")
        db.unbook_seat(ev5_id, 1001, "mario")

        # Event 6: same day written in DD-MM-YYYY format ("05-09-2026")
        ev6_id = self._event(title="Blades in the Dark", normalized_date="05-09-2026")

        # Mario subscribing to ev2
        conflicts = db.get_user_conflicting_events(ev2_id, user_id=1001, username="mario")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["id"], event_id)
        self.assertEqual(conflicts[0]["title"], "Avventura D&D")

        # Mario subscribing to ev6 (cross-format DD-MM-YYYY vs YYYY-MM-DD)
        conflicts_ev6 = db.get_user_conflicting_events(ev6_id, user_id=1001, username="mario")
        self.assertEqual(len(conflicts_ev6), 1)
        self.assertEqual(conflicts_ev6[0]["id"], event_id)

        # Querying with only user_id or only username
        conflicts_uid_only = db.get_user_conflicting_events(ev2_id, user_id=1001, username=None)
        self.assertEqual(len(conflicts_uid_only), 1)
        conflicts_uname_only = db.get_user_conflicting_events(ev2_id, user_id=None, username="@mario")
        self.assertEqual(len(conflicts_uname_only), 1)

        # The event itself is excluded
        conflicts_self = db.get_user_conflicting_events(event_id, user_id=1001, username="mario")
        self.assertEqual(len(conflicts_self), 0)

        # If Mario books ev2 as well, then queries for ev6 (a 3rd event that day)
        db.book_seat(ev2_id, 1001, "mario")
        conflicts_multi = db.get_user_conflicting_events(ev6_id, user_id=1001, username="mario")
        self.assertEqual(len(conflicts_multi), 2)
        conflict_ids = [c["id"] for c in conflicts_multi]
        self.assertIn(event_id, conflict_ids)
        self.assertIn(ev2_id, conflict_ids)


class TestUserUpcomingReservations(TempDBMixin, unittest.TestCase):
    def _event(self, days=1, status="approved", **overrides):
        day = (date.today() + timedelta(days=days)).strftime("%d-%m-%Y")
        return create_event(status=status, normalized_date=day, date=day, **overrides)

    def _mine(self, user_id=1001, username="mario"):
        return [(ev["id"], ev["my_seats"]) for ev in db.get_user_upcoming_reservations(user_id, username)]

    def test_lists_today_and_future_events_sorted_with_my_seats(self):
        later, today, soon = self._event(days=5), self._event(days=0), self._event(days=2)
        for event_id, seats in ((later, 1), (today, 2), (soon, 1)):
            for _ in range(seats):
                db.book_seat(event_id, 1001, "mario")

        self.assertEqual(self._mine(), [(today, 2), (soon, 1), (later, 1)])

    def test_past_cancelled_and_discarded_events_are_left_out(self):
        past = self._event(days=-1)
        cancelled = self._event(status="cancelled")
        discarded = self._event(status="discarded")
        pending = self._event(status="pending")
        for event_id in (past, cancelled, discarded, pending):
            db.book_seat(event_id, 1001, "mario")

        self.assertEqual(self._mine(), [])

    def test_released_seats_and_other_users_are_left_out(self):
        released, other = self._event(), self._event()
        db.book_seat(released, 1001, "mario")
        db.unbook_seat(released, 1001, "mario")
        db.book_seat(other, 2002, "luigi")

        self.assertEqual(self._mine(), [])
        self.assertEqual([ev["id"] for ev in db.get_user_upcoming_reservations(2002, "luigi")], [other])

    def test_matches_by_user_id_even_when_the_username_changed(self):
        event_id = self._event()
        db.book_seat(event_id, 1001, "mario")

        self.assertEqual(self._mine(user_id=1001, username="mario_new"), [(event_id, 1)])
        self.assertEqual(self._mine(user_id=1001, username=None), [(event_id, 1)])

    def test_matches_admin_added_rows_by_username_only(self):
        event_id = self._event()
        db.admin_add_subscriber(event_id, "@Mario", seats=2)

        self.assertEqual(self._mine(user_id=1001, username="mario"), [(event_id, 2)])
        self.assertEqual(self._mine(user_id=1001, username="someone_else"), [])

    def test_eventbrite_attendees_never_match(self):
        event_id = self._event()
        db.apply_eventbrite_order(event_id, "ord-1", "mario", 1)

        self.assertEqual(self._mine(), [])

    def test_no_identity_returns_nothing(self):
        event_id = self._event()
        db.book_seat(event_id, 1001, "mario")

        self.assertEqual(db.get_user_upcoming_reservations(None, None), [])
        self.assertEqual(db.get_user_upcoming_reservations(None, "  @ "), [])

if __name__ == "__main__":
    unittest.main()
