import unittest

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


if __name__ == "__main__":
    unittest.main()
