import unittest
from unittest.mock import patch

from core.eventbrite import eventbrite_venue_ids, get_venue
from tests.support.config import eventbrite_credentials


class TestVenues(unittest.TestCase):
    @patch("core.eventbrite.venues.eb_get", return_value={"id": "v1", "name": "Gilda"})
    def test_get_venue(self, mock_get):
        self.assertEqual(get_venue("v1")["name"], "Gilda")
        mock_get.assert_called_once_with("/venues/v1/")

    def test_default_first_then_alternatives(self):
        with eventbrite_credentials(EVENTBRITE_VENUE_ID="a", EVENTBRITE_VENUE_ID_ALTERNATIVES=["b", "c"]):
            self.assertEqual(eventbrite_venue_ids(), ["a", "b", "c"])

    def test_repeated_ids_are_dropped(self):
        with eventbrite_credentials(EVENTBRITE_VENUE_ID="a", EVENTBRITE_VENUE_ID_ALTERNATIVES=["a", "b", "b"]):
            self.assertEqual(eventbrite_venue_ids(), ["a", "b"])

    def test_without_alternatives_only_the_default(self):
        with eventbrite_credentials(EVENTBRITE_VENUE_ID="a"):
            self.assertEqual(eventbrite_venue_ids(), ["a"])


if __name__ == "__main__":
    unittest.main()
