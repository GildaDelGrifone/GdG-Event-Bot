import unittest

import core.db as db
from tests.support.db import TempDBMixin, create_event


class TestEventbriteMutes(TempDBMixin, unittest.TestCase):
    def test_muting_twice_keeps_one_row(self):
        event_id = create_event(status="approved")
        first = db.mute_eventbrite_name(event_id, "Giovanni F.")
        self.assertIsNotNone(first)
        self.assertEqual(db.mute_eventbrite_name(event_id, "Giovanni F."), first)
        self.assertEqual([m["name"] for m in db.get_eventbrite_mutes(event_id)], ["Giovanni F."])

    def test_mutes_are_per_event(self):
        first, second = create_event(status="approved"), create_event(status="approved")
        db.mute_eventbrite_name(first, "Giovanni F.")
        self.assertEqual(db.get_eventbrite_mutes(second), [])

    def test_get_and_unmute(self):
        event_id = create_event(status="approved")
        mute_id = db.mute_eventbrite_name(event_id, "Giovanni F.")
        mute = db.get_eventbrite_mute(mute_id)
        self.assertEqual((mute["event_id"], mute["name"]), (event_id, "Giovanni F."))

        self.assertTrue(db.unmute_eventbrite(mute_id))
        self.assertIsNone(db.get_eventbrite_mute(mute_id))
        self.assertFalse(db.unmute_eventbrite(mute_id))  # already gone

    def test_deleting_the_event_deletes_its_mutes(self):
        event_id = create_event(status="approved")
        mute_id = db.mute_eventbrite_name(event_id, "Giovanni F.")
        db.delete_event(event_id)
        self.assertIsNone(db.get_eventbrite_mute(mute_id))


if __name__ == "__main__":
    unittest.main()
