import unittest

import core.db as db
from tests.support.db import TempDBMixin


class TestSettings(TempDBMixin, unittest.TestCase):
    def test_unset_key_gives_the_default(self):
        self.assertEqual(db.get_setting("missing", "fallback"), "fallback")

    def test_values_round_trip_and_overwrite(self):
        self.assertTrue(db.set_setting("is_paused", True))
        self.assertIs(db.get_setting("is_paused"), True)
        db.set_setting("is_paused", False)
        self.assertIs(db.get_setting("is_paused", True), False)

    def test_a_stored_none_is_not_the_default(self):
        db.set_setting("eventbrite_venue", None)
        self.assertIsNone(db.get_setting("eventbrite_venue", "v1"))


    def test_clear_removes_every_key(self):
        db.set_setting("is_paused", True)
        db.set_setting("eventbrite_venue", "v2")
        self.assertTrue(db.clear_settings())
        self.assertEqual(db.get_setting("is_paused", "unset"), "unset")
        self.assertEqual(db.get_setting("eventbrite_venue", "unset"), "unset")

if __name__ == "__main__":
    unittest.main()
