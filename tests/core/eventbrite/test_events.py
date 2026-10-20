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


@patch("core.eventbrite.events.eb_delete")
class TestDeleteEvent(unittest.TestCase):
    def test_deletes_the_event(self, mock_delete):
        self.assertTrue(events.delete_eventbrite_event("42"))
        mock_delete.assert_called_once_with("/events/42/")

    def test_a_refusal_propagates(self, mock_delete):
        from core.eventbrite import EventbriteError
        mock_delete.side_effect = EventbriteError(400, "CANNOT_DELETE", "has orders")
        with self.assertRaises(EventbriteError):
            events.delete_eventbrite_event("42")


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


    def test_capacity_with_free_seats_sets_the_total_and_reopens_sales(self, mock_post):
        end = datetime(2099, 11, 7, tzinfo=timezone.utc)
        tickets.update_ticket_capacity("1", "tc1", 3, 1, end)
        mock_post.assert_called_with("/events/1/ticket_classes/tc1/", json={"ticket_class": {
            "quantity_total": 3, "hidden": False, "sales_end": "2099-11-07T00:00:00Z"}})

    def test_capacity_without_seats_and_with_sales_keeps_the_total_at_sold_and_ends_sales(self, mock_post):
        now = datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc)
        tickets.update_ticket_capacity("1", "tc1", 2, 2, None, now=now)
        mock_post.assert_called_with("/events/1/ticket_classes/tc1/", json={"ticket_class": {
            "sales_end": "2099-01-01T12:02:00Z", "quantity_total": 2}})

    def test_capacity_without_seats_and_without_sales_hides_the_ticket_and_never_sends_zero(self, mock_post):
        now = datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc)
        tickets.update_ticket_capacity("1", "tc1", 0, 0, None, now=now)
        mock_post.assert_called_with("/events/1/ticket_classes/tc1/", json={"ticket_class": {
            "sales_end": "2099-01-01T12:02:00Z", "hidden": True}})


if __name__ == "__main__":
    unittest.main()
