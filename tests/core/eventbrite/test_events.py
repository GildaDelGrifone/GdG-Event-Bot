import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from core.eventbrite import events, tickets
from tests.support.config import eventbrite_credentials


@patch("core.eventbrite.events.eb_post")
@patch("core.eventbrite.events.eb_get")
class TestEvents(unittest.TestCase):
    def test_create_and_update_wrap_the_event_object(self, _get, mock_post):
        mock_post.return_value = {"id": "1", "url": "https://eb/1"}
        with eventbrite_credentials():
            self.assertEqual(events.create_event({"summary": "s"}), {"id": "1", "url": "https://eb/1"})
            events.update_event("1", {"logo_id": "m"})
        self.assertEqual(mock_post.call_args_list[0].args, ("/organizations/org1/events/",))
        self.assertEqual(mock_post.call_args_list[0].kwargs["json"], {"event": {"summary": "s"}})
        self.assertEqual(mock_post.call_args_list[1].args, ("/events/1/",))
        self.assertEqual(mock_post.call_args_list[1].kwargs["json"], {"event": {"logo_id": "m"}})

    def test_status_changes_return_the_api_flag(self, _get, mock_post):
        mock_post.side_effect = [{"published": True}, {"unpublished": True}, {"canceled": True}, {}]
        self.assertTrue(events.publish_event("1"))
        self.assertTrue(events.unpublish_event("1"))
        self.assertTrue(events.cancel_event("1"))
        self.assertFalse(events.publish_event("1"))
        self.assertEqual([c.args[0] for c in mock_post.call_args_list],
                         ["/events/1/publish/", "/events/1/unpublish/", "/events/1/cancel/", "/events/1/publish/"])

    def test_get_event_expands_ticket_classes(self, mock_get, _post):
        mock_get.return_value = {"status": "live"}
        self.assertEqual(events.get_event("1"), {"status": "live"})
        mock_get.assert_called_once_with("/events/1/", params={"expand": "ticket_classes"})

    def test_set_description_writes_all_modules_at_the_given_version(self, _get, mock_post):
        mock_post.return_value = {}
        self.assertEqual(events.set_description("1", [{"type": "text"}], 3), 3)
        mock_post.assert_called_once_with(
            "/events/1/structured_content/3/",
            json={"modules": [{"type": "text"}], "publish": True, "purpose": "listing"})


@patch("core.eventbrite.tickets.eb_post")
class TestTickets(unittest.TestCase):
    def test_create_free_ticket_class(self, mock_post):
        mock_post.return_value = {"id": "tc1"}
        end = datetime(2026, 11, 7, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(tickets.create_free_ticket_class("1", 4, end), {"id": "tc1"})
        mock_post.assert_called_once_with("/events/1/ticket_classes/", json={"ticket_class": {
            "name": "Posto", "free": True, "quantity_total": 4, "sales_end": "2026-11-07T00:00:00Z"}})

    def test_create_without_sales_end_and_update_quantity(self, mock_post):
        tickets.create_free_ticket_class("1", 4)
        self.assertNotIn("sales_end", mock_post.call_args.kwargs["json"]["ticket_class"])
        tickets.update_ticket_quantity("1", "tc1", 2)
        mock_post.assert_called_with("/events/1/ticket_classes/tc1/", json={"ticket_class": {"quantity_total": 2}})


if __name__ == "__main__":
    unittest.main()
