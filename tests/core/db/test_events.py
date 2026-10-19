import unittest
from datetime import datetime, timedelta

import core.db as db
from tests.support.db import TempDBMixin, create_event


class TestDeleteEvent(TempDBMixin, unittest.TestCase):
    def test_delete_event_cleans_event_and_reservations(self):
        event_id = create_event(original_text="test text", title="Old Event", host="Old Host", description="Old Desc")
        db.book_seat(event_id, 12345, "testuser")
        self.assertIsNotNone(db.get_event(event_id))
        self.assertEqual(len(db.get_reservations_for_event(event_id)), 1)

        res = db.delete_event(event_id)
        self.assertTrue(res)
        self.assertIsNone(db.get_event(event_id))
        self.assertEqual(len(db.get_reservations_for_event(event_id)), 0)


class TestRoleplayTypeDatabase(TempDBMixin, unittest.TestCase):
    def test_insert_and_get_is_roleplay(self):
        ev_id = db.insert_event({"title": "Cyberpunk Red", "host": "Mike", "is_roleplay": True}, None, "Cyberpunk Red raw")
        self.assertEqual(db.get_event(ev_id)["is_roleplay"], 1)

        ev_bg_id = db.insert_event({"title": "Wingspan", "host": "Elizabeth", "is_roleplay": False}, None, "Wingspan raw")
        self.assertEqual(db.get_event(ev_bg_id)["is_roleplay"], 0)

    def test_update_event_field_is_roleplay(self):
        ev_id = db.insert_event({"title": "Game Night", "host": "Alex", "is_roleplay": 0}, None, "Game Night raw")
        self.assertEqual(db.get_event(ev_id)["is_roleplay"], 0)

        success = db.update_event_field(ev_id, "is_roleplay", 1)
        self.assertTrue(success)
        self.assertEqual(db.get_event(ev_id)["is_roleplay"], 1)

        success = db.update_event_field(ev_id, "is_roleplay", 0)
        self.assertTrue(success)
        self.assertEqual(db.get_event(ev_id)["is_roleplay"], 0)


class TestEventbriteInfo(TempDBMixin, unittest.TestCase):
    def test_set_and_clear_eventbrite_info(self):
        event_id = db.insert_event({"title": "T"}, None, "raw")
        self.assertTrue(db.set_eventbrite_info(event_id, eventbrite_event_id="123", eventbrite_status="draft",
                                               eventbrite_content_version=2))
        ev = db.get_event(event_id)
        self.assertEqual((ev["eventbrite_event_id"], ev["eventbrite_status"], ev["eventbrite_content_version"]),
                         ("123", "draft", 2))

        self.assertTrue(db.clear_eventbrite_info(event_id))
        ev = db.get_event(event_id)
        self.assertIsNone(ev["eventbrite_event_id"])
        self.assertIsNone(ev["eventbrite_status"])
        self.assertEqual(ev["eventbrite_content_version"], 0)

    def test_set_eventbrite_info_rejects_other_columns(self):
        event_id = db.insert_event({"title": "T"}, None, "raw")
        self.assertFalse(db.set_eventbrite_info(event_id, title="hack"))
        self.assertFalse(db.set_eventbrite_info(event_id))
        self.assertFalse(db.update_event_field(event_id, "eventbrite_event_id", "1"))
        self.assertEqual(db.get_event(event_id)["title"], "T")

    def test_tracked_events_filter_by_link_status_and_date(self):
        today = datetime.now()
        fmt = "%d-%m-%Y"

        def make(delta_days, status="approved", linked=True):
            event_id = db.insert_event(
                {"title": f"E{delta_days}", "normalized_date": (today + timedelta(days=delta_days)).strftime(fmt)},
                None, "raw")
            db.update_event_status(event_id, status)
            if linked:
                db.set_eventbrite_info(event_id, eventbrite_event_id=f"eb{event_id}")
            return event_id

        keep = {make(0), make(3), make(-1), make(0, status="cancelled")}
        make(-2)
        make(1, linked=False)
        make(1, status="pending")
        make(1, status="discarded")
        self.assertEqual({e["id"] for e in db.get_eventbrite_tracked_events()}, keep)


if __name__ == "__main__":
    unittest.main()
