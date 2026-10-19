import unittest
from unittest.mock import MagicMock, patch

from core.eventbrite import EventbriteError, eventbrite_enabled
from core.eventbrite.client import API_BASE, eb_get, eb_post, paginate
from tests.support.config import eventbrite_credentials, patched_config


def response(status_code=200, json_value=None, json_error=False):
    result = MagicMock(status_code=status_code)
    if json_error:
        result.json.side_effect = ValueError("no json")
    else:
        result.json.return_value = json_value if json_value is not None else {}
    return result


class TestEnabled(unittest.TestCase):
    def test_requires_token_organization_and_venue(self):
        with eventbrite_credentials():
            self.assertTrue(eventbrite_enabled())
        for missing in ("EVENTBRITE_TOKEN", "EVENTBRITE_ORGANIZATION_ID", "EVENTBRITE_VENUE_ID"):
            with self.subTest(missing=missing), eventbrite_credentials(**{missing: None}):
                self.assertFalse(eventbrite_enabled())

    def test_disabled_by_default(self):
        with patched_config(EVENTBRITE_TOKEN=None, EVENTBRITE_ORGANIZATION_ID=None, EVENTBRITE_VENUE_ID=None):
            self.assertFalse(eventbrite_enabled())


class TestRequests(unittest.TestCase):
    @patch("core.eventbrite.client.requests.get", return_value=response(200, {"ok": 1}))
    def test_get_sends_bearer_token_and_timeout(self, mock_get):
        with eventbrite_credentials():
            self.assertEqual(eb_get("/users/me/", {"a": 1}), {"ok": 1})
        mock_get.assert_called_once_with(
            f"{API_BASE}/users/me/", headers={"Authorization": "Bearer eb-token"}, params={"a": 1}, timeout=30)

    @patch("core.eventbrite.client.requests.post", return_value=response(200, {"published": True}))
    def test_post_sends_json(self, mock_post):
        with eventbrite_credentials():
            self.assertEqual(eb_post("/events/1/publish/", json={"x": 1}), {"published": True})
        self.assertEqual(mock_post.call_args.kwargs["json"], {"x": 1})

    @patch("core.eventbrite.client.requests.post", return_value=response(200, json_error=True))
    def test_empty_success_body_is_an_empty_dict(self, _post):
        with eventbrite_credentials():
            self.assertEqual(eb_post("/x/"), {})

    @patch("core.eventbrite.client.requests.post")
    def test_error_is_parsed_from_the_error_constant(self, mock_post):
        mock_post.return_value = response(429, {"error": "HIT_RATE_LIMIT", "error_description": "slow down"})
        with eventbrite_credentials(), self.assertRaises(EventbriteError) as ctx:
            eb_post("/x/")
        self.assertEqual((ctx.exception.status_code, ctx.exception.error, ctx.exception.description),
                         (429, "HIT_RATE_LIMIT", "slow down"))

    @patch("core.eventbrite.client.requests.get", return_value=response(502, json_error=True))
    def test_error_without_json_body(self, _get):
        with eventbrite_credentials(), self.assertRaises(EventbriteError) as ctx:
            eb_get("/x/")
        self.assertEqual((ctx.exception.status_code, ctx.exception.error), (502, "HTTP_502"))


class TestPaginate(unittest.TestCase):
    @patch("core.eventbrite.client.requests.get")
    def test_follows_continuation_until_no_more_items(self, mock_get):
        mock_get.side_effect = [
            response(200, {"orders": [1, 2], "pagination": {"has_more_items": True, "continuation": "c1"}}),
            response(200, {"orders": [3], "pagination": {"has_more_items": True, "continuation": "c2"}}),
            response(200, {"orders": [4], "pagination": {"has_more_items": False}}),
        ]
        with eventbrite_credentials():
            self.assertEqual(list(paginate("/events/1/orders/", {"status": "all"}, "orders")), [1, 2, 3, 4])
        sent = [call.kwargs["params"] for call in mock_get.call_args_list]
        self.assertEqual(sent, [{"status": "all"}, {"status": "all", "continuation": "c1"},
                                {"status": "all", "continuation": "c2"}])

    @patch("core.eventbrite.client.requests.get", return_value=response(200, {}))
    def test_missing_key_and_pagination_yield_nothing(self, _get):
        with eventbrite_credentials():
            self.assertEqual(list(paginate("/x/", None, "orders")), [])


if __name__ == "__main__":
    unittest.main()
