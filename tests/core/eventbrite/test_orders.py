import unittest
from unittest.mock import patch

from core.eventbrite.orders import fetch_active_orders


def attendee(first, last, **flags):
    return {"id": "a", "profile": {"first_name": first, "last_name": last, "email": "secret@example.com"}, **flags}


class TestFetchActiveOrders(unittest.TestCase):
    @patch("core.eventbrite.orders.paginate")
    def test_counts_only_active_attendees_and_skips_empty_orders(self, mock_paginate):
        mock_paginate.return_value = iter([
            {"id": 1, "attendees": [attendee("Mario", "Rossi"), attendee("Luigi", "Verdi")]},
            {"id": 2, "attendees": [attendee("Anna", "Bianchi", cancelled=True), attendee("Paola", "Neri")]},
            {"id": 3, "attendees": [attendee("Gino", "Gialli", refunded=True)]},
            {"id": 4, "attendees": [attendee("Zoe", "Blu", cancelled=True)]},
            {"id": 5, "attendees": []},
            {"id": 6},
        ])
        self.assertEqual(fetch_active_orders("eb1"), {"1": ("Mario R.", 2), "2": ("Paola N.", 1)})
        mock_paginate.assert_called_once_with(
            "/events/eb1/orders/", {"status": "all_not_deleted", "expand": "attendees"}, "orders")

    @patch("core.eventbrite.orders.paginate")
    def test_falls_back_to_the_order_name_and_never_keeps_emails(self, mock_paginate):
        mock_paginate.return_value = iter([
            {"id": 7, "first_name": "Carla", "last_name": "Rosa", "attendees": [{"id": "x"}]},
        ])
        orders = fetch_active_orders("eb1")
        self.assertEqual(orders, {"7": ("Carla R.", 1)})
        self.assertNotIn("secret", repr(orders))


if __name__ == "__main__":
    unittest.main()
