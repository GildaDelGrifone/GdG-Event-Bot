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
        db.set_eventbrite_info(make(2), eventbrite_status="canceled")  # nothing can change on it any more
        make(1, linked=False)
        make(1, status="pending")
        make(1, status="discarded")
        self.assertEqual({e["id"] for e in db.get_eventbrite_tracked_events()}, keep)


class TestEventbriteCleanupCandidates(TempDBMixin, unittest.TestCase):
    def make(self, delta_days, eb_status, status="approved", linked=True, dated=True):
        today = datetime.now()
        fields = {"title": f"E{delta_days}{eb_status}"}
        if dated:
            fields["normalized_date"] = (today + timedelta(days=delta_days)).strftime("%d-%m-%Y")
        event_id = db.insert_event(fields, None, "raw")
        db.update_event_status(event_id, status)
        if linked:
            db.set_eventbrite_info(event_id, eventbrite_event_id=f"eb{event_id}", eventbrite_status=eb_status)
        return event_id

    def test_candidates_are_cancelled_unpublished_or_closed_events_dated_today_or_earlier(self):
        now = datetime.now()
        keep = {
            self.make(0, "canceled"), self.make(-1, "unpublished"), self.make(-30, "closed"),
            self.make(0, "canceled", status="cancelled"),  # whatever the Telegram status
            self.make(0, "unpublished", status="cancelled"),
        }
        self.make(1, "canceled")  # future: left alone until its day
        self.make(0, "live")
        self.make(0, "draft")
        self.make(0, "canceled", linked=False)
        self.make(0, "canceled", dated=False)
        day = (now.year, now.month, now.day)
        self.assertEqual({e["id"] for e in db.get_eventbrite_cleanup_candidates(day)}, keep)

    def test_the_day_is_inclusive_and_configurable(self):
        event_id = self.make(0, "canceled")
        today = datetime.now()
        day = (today.year, today.month, today.day)
        self.assertEqual([e["id"] for e in db.get_eventbrite_cleanup_candidates(day)], [event_id])
        yesterday = today - timedelta(days=1)
        self.assertEqual(db.get_eventbrite_cleanup_candidates((yesterday.year, yesterday.month, yesterday.day)), [])


if __name__ == "__main__":
    unittest.main()
