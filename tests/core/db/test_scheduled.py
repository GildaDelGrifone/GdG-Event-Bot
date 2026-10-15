import unittest

import core.db as db
from tests.support.db import TempDBMixin


class TestScheduledEvents(TempDBMixin, unittest.TestCase):
    def test_content_update_only_touches_given_columns(self):
        sched_id = db.insert_scheduled_event("Titolo", "testo", image_path="/a.jpg", schedule_days=["Lunedì"])
        db.update_scheduled_event_content(sched_id, "nuovo testo")
        ev = db.get_scheduled_event(sched_id)
        self.assertEqual((ev["text"], ev["image_path"], ev["title"]), ("nuovo testo", "/a.jpg", "Titolo"))
        self.assertEqual(ev["schedule_days"], ["Lunedì"])

        db.update_scheduled_event_content(sched_id, "t2", title="Nuovo")
        self.assertEqual(db.get_scheduled_event(sched_id)["title"], "Nuovo")

    def test_matches_weekday_or_specific_date(self):
        weekly = db.insert_scheduled_event("A", "a", schedule_days=["Mercoledì"])
        dated = db.insert_scheduled_event("B", "b", specific_date="Venerdì 09-10-2026 21:00")
        db.insert_scheduled_event("C", "c", schedule_days=["Lunedì"])
        ids = {ev["id"] for ev in db.get_scheduled_events_for_date("09-10-2026", "mercoledì")}
        self.assertEqual(ids, {weekly, dated})

    def test_scheduled_events_db_crud(self):
        sched_id = db.insert_scheduled_event(
            title="D&D One-Shot",
            text="Titolo: D&D One-Shot\nData: 09-10-2026 21:00\nPosti: 4/4",
            image_path="/tmp/test.jpg",
            schedule_days=["Lunedì", "Venerdì"],
            specific_date="09-10-2026 21:00",
        )
        self.assertIsNotNone(sched_id)

        ev = db.get_scheduled_event(sched_id)
        self.assertEqual(ev["title"], "D&D One-Shot")
        self.assertEqual(ev["schedule_days"], ["Lunedì", "Venerdì"])
        self.assertEqual(ev["specific_date"], "09-10-2026 21:00")

        # Update days
        ok = db.update_scheduled_event_days(sched_id, ["Mercoledì", "Sabato"])
        self.assertTrue(ok)
        self.assertEqual(db.get_scheduled_event(sched_id)["schedule_days"], ["Mercoledì", "Sabato"])

        # Update specific date
        ok = db.update_scheduled_event_specific_date(sched_id, "15-10-2026 20:30")
        self.assertTrue(ok)
        self.assertEqual(db.get_scheduled_event(sched_id)["specific_date"], "15-10-2026 20:30")

        # Update content (/event_schedule_update)
        ok = db.update_scheduled_event_content(sched_id, "Nuovo testo", title="Nuovo Titolo")
        self.assertTrue(ok)
        ev = db.get_scheduled_event(sched_id)
        self.assertEqual(ev["title"], "Nuovo Titolo")
        self.assertEqual(ev["text"], "Nuovo testo")

        # Get for date matching
        matches = db.get_scheduled_events_for_date("15-10-2026", "Mercoledì")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["id"], sched_id)

        # Delete
        db.delete_scheduled_event(sched_id)
        self.assertIsNone(db.get_scheduled_event(sched_id))


if __name__ == "__main__":
    unittest.main()
