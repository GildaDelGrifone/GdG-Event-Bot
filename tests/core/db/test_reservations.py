import unittest

import core.db as db
from core.db.reservations import normalize_identity
from tests.support.db import SUBSCRIBED_EVENT, TempDBMixin, create_subscribed_event


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


if __name__ == "__main__":
    unittest.main()
