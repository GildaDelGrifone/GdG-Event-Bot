import unittest
from unittest.mock import MagicMock, patch

from bot.event_generator.bgg import bgg_image_url, fetch_bgg_game_image, pick_best_bgg_item
from tests.support.config import patched_config


def http_response(status_code=200, json=None, content=None, text=None):
    response = MagicMock(status_code=status_code)
    if json is not None:
        response.json.return_value = json
    if content is not None:
        response.content = content
    if text is not None:
        response.text = text
    return response


class TestFetchGameImage(unittest.TestCase):
    def _fetch(self, game, responses, token="test_token"):
        """Runs fetch_bgg_game_image(game) with requests.get answering `responses` in order; returns (result, get)."""
        with patched_config(BGG_API_TOKEN=token), \
             patch("bot.event_generator.bgg.requests.get", side_effect=responses) as mock_get:
            return fetch_bgg_game_image(game), mock_get

    def test_fetch_bgg_game_image_exact_match(self):
        result, mock_get = self._fetch("Catan", [
            http_response(json={"items": [
                {"objectid": 999, "name": "54x80mm Catan Sleeves"},
                {"objectid": 13, "name": "Catan"},
            ]}),
            http_response(json={"item": {
                "imageurl": "https://example.com/catan_thumb.jpg",
                "images": {"original": "https://example.com/catan_orig.jpg"},
            }}),
            http_response(content=b"CATAN_IMAGE_BYTES"),
        ])
        self.assertEqual(result, b"CATAN_IMAGE_BYTES")
        self.assertEqual(mock_get.call_count, 3)
        # The BGG token is sent in the search request headers
        search_headers = mock_get.call_args_list[0][1]["headers"]
        self.assertEqual(search_headers.get("Authorization"), "Bearer test_token")
        # The detail URL uses objectid 13 (exact match)
        self.assertIn("objectid=13", mock_get.call_args_list[1][0][0])
        self.assertEqual(mock_get.call_args_list[2][0][0], "https://example.com/catan_orig.jpg")

    def test_fetch_bgg_game_image_filters_accessory(self):
        result, mock_get = self._fetch("Root", [
            http_response(json={"items": [
                {"objectid": 111, "name": "Root Playmat Neoprene"},
                {"objectid": 222, "name": "Root: A Game of Woodland Might and Right"},
            ]}),
            http_response(json={"item": {"imageurl": "//example.com/root.jpg"}}),
            http_response(content=b"ROOT_IMAGE"),
        ])
        self.assertEqual(result, b"ROOT_IMAGE")
        # 111 is an accessory, so objectid 222 is chosen
        self.assertIn("objectid=222", mock_get.call_args_list[1][0][0])
        # A leading // is prefixed with https:
        self.assertEqual(mock_get.call_args_list[2][0][0], "https://example.com/root.jpg")

    def test_fetch_bgg_game_image_empty_or_error(self):
        self.assertIsNone(fetch_bgg_game_image(""))
        with patched_config(BGG_API_TOKEN="test_token"), patch("bot.event_generator.bgg.requests.get") as mock_get:
            mock_get.return_value.status_code = 404
            self.assertIsNone(fetch_bgg_game_image("NonexistentGame"))

    def test_fetch_game_image_fallback_wikipedia(self):
        result, mock_get = self._fetch("Catan", [
            http_response(json={"query": {"search": [{"title": "Catan"}]}}),
            http_response(json={"thumbnail": {"source": "https://upload.wikimedia.org/catan.jpg"}}),
            http_response(content=b"X" * 600),
        ], token=None)
        self.assertEqual(result, b"X" * 600)
        self.assertEqual(mock_get.call_count, 3)

    def test_fetch_game_image_fallback_bing_when_wikipedia_empty(self):
        result, _mock_get = self._fetch("Champions of Midgard", [
            http_response(json={"query": {"search": []}}),
            http_response(text='<a class="thumb" murl="https://example.com/midgard.jpg"></a>'),
            http_response(content=b"Y" * 1200),
        ], token=None)
        self.assertEqual(result, b"Y" * 1200)

    def test_fetch_game_image_bgg_error_falls_back_to_web(self):
        result, _mock_get = self._fetch("Monopoly", [
            http_response(status_code=401),
            http_response(json={"query": {"search": [{"title": "Monopoly"}]}}),
            http_response(json={"thumbnail": {"source": "https://upload.wikimedia.org/mono.jpg"}}),
            http_response(content=b"M" * 600),
        ], token="bad_token")
        self.assertEqual(result, b"M" * 600)


class TestBggHelpers(unittest.TestCase):
    def test_pick_best_bgg_item(self):
        items = [{"name": "Catan Sleeves"}, {"name": "Catan: Seafarers"}, {"name": "Catan"}]
        self.assertEqual(pick_best_bgg_item(items, "Catan")["name"], "Catan")
        self.assertEqual(pick_best_bgg_item(items[:2], "catan")["name"], "Catan: Seafarers")
        self.assertEqual(pick_best_bgg_item([{"name": "Dice Bag"}], "x")["name"], "Dice Bag")

    def test_bgg_image_url(self):
        self.assertEqual(bgg_image_url({"images": {"original": "//cf.geekdo.com/a.jpg"}}), "https://cf.geekdo.com/a.jpg")
        self.assertEqual(bgg_image_url({"imageurl": "https://x/b.jpg"}), "https://x/b.jpg")
        self.assertIsNone(bgg_image_url({}))


if __name__ == "__main__":
    unittest.main()
