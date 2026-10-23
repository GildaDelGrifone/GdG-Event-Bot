import unittest
from unittest.mock import patch

from core.eventbrite import collections


@patch("core.eventbrite.collections.eb_delete")
@patch("core.eventbrite.collections.eb_post")
class TestCollections(unittest.TestCase):
    def test_create_collection(self, mock_post, _delete):
        mock_post.return_value = {"id": "9", "name": "Giochi di ruolo"}
        self.assertEqual(collections.create_collection("Giochi di ruolo", "o1")["id"], "9")
        mock_post.assert_called_once_with("/collections/", json={"name": "Giochi di ruolo", "organizer_id": "o1"})

    def test_add_event_sends_the_id_as_a_string(self, mock_post, _delete):
        collections.add_event_to_collection("9", 123)
        mock_post.assert_called_once_with("/collections/9/events/", json={"event_ids": "123"})

    def test_remove_event(self, _post, mock_delete):
        collections.remove_event_from_collection("9", "123")
        mock_delete.assert_called_once_with("/collections/9/events/", json={"event_ids": "123"})


if __name__ == "__main__":
    unittest.main()
