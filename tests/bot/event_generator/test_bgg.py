import html
import json
import unittest
from unittest.mock import MagicMock, patch

from bot.event_generator.bgg import (
    bgg_image_url, bgg_item_matches, fetch_bgg_game_image, image_matches_game, mentions_game, pick_best_bgg_item,
    rank_wikidata_entities,
)
from core.ai_parser import GeminiQuotaError
from tests.support.config import patched_config
from tests.support.images import image_bytes


def http_response(status_code=200, json=None, content=None, text=None):
    response = MagicMock(status_code=status_code)
    if json is not None:
        response.json.return_value = json
    if content is not None:
        response.content = content
    if text is not None:
        response.text = text
    return response


IMG = b"I" * 1200


def wikidata_search(*ids):
    return http_response(json={"query": {"search": [{"title": i} for i in ids]}})


def bgg_item(name, alternates=(), subtype="boardgame", image="https://cf.geekdo-images.com/box.jpg"):
    return http_response(json={"item": {
        "name": name, "subtype": subtype, "alternatenames": [{"name": n} for n in alternates],
        "images": {"original": image},
    }})


def bing_result(murl, title, purl):
    meta = json.dumps({"murl": murl, "t": title, "purl": purl})
    return f'<a class="iusc" m="{html.escape(meta)}"></a>'


class TestFetchGameImage(unittest.TestCase):
    def _fetch(self, game, responses, token="test_token", bgg_id=None):
        """Runs fetch_bgg_game_image(game) with requests.get answering `responses` in order; returns (result, get)."""
        with patched_config(BGG_API_TOKEN=token), \
             patch("bot.event_generator.bgg.requests.get", side_effect=responses) as mock_get:
            return fetch_bgg_game_image(game, bgg_id=bgg_id), mock_get

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

    def test_fetch_game_image_bgg_id_hint_without_token(self):
        result, mock_get = self._fetch("Champions of Midgard", [
            bgg_item("Champions of Midgard", image="//cf.geekdo-images.com/midgard.jpg"),
            http_response(content=IMG),
        ], token=None, bgg_id=172287)
        self.assertEqual(result, IMG)
        self.assertIn("objectid=172287", mock_get.call_args_list[0][0][0])
        self.assertNotIn("Authorization", mock_get.call_args_list[0][1]["headers"])
        self.assertEqual(mock_get.call_args_list[1][0][0], "https://cf.geekdo-images.com/midgard.jpg")

    def test_fetch_game_image_wrong_bgg_id_hint_falls_back(self):
        with patched_config(GEMINI_API_KEY=None):
            result, mock_get = self._fetch("Sky Team", [
                bgg_item("Vossheim's Holdouts"),
                wikidata_search(),
                http_response(json={"query": {"search": []}}),
            ], token=None, bgg_id=373103)
        self.assertIsNone(result)
        # No image download for the wrong game
        self.assertEqual(mock_get.call_count, 3)

    def test_fetch_game_image_wikidata_bgg_id_first(self):
        result, mock_get = self._fetch("Root", [
            wikidata_search("Q101242941"),
            http_response(json={"entities": {"Q101242941": {
                "id": "Q101242941", "labels": {"en": {"value": "Root"}},
                "sitelinks": {"enwiki": {"title": "Root (board game)"}},
                "claims": {"P2339": [{"mainsnak": {"datavalue": {"value": "237182"}}}]},
            }}}),
            bgg_item("Root", image="https://cf.geekdo-images.com/root_box.jpg"),
            http_response(content=IMG),
        ], token=None)
        self.assertEqual(result, IMG)
        self.assertIn("objectid=237182", mock_get.call_args_list[2][0][0])
        self.assertEqual(mock_get.call_args_list[3][0][0], "https://cf.geekdo-images.com/root_box.jpg")

    def test_fetch_game_image_wikidata_bgg_unavailable_uses_wikipedia(self):
        result, mock_get = self._fetch("Root", [
            wikidata_search("Q101242941"),
            http_response(json={"entities": {"Q101242941": {
                "id": "Q101242941", "sitelinks": {"enwiki": {"title": "Root (board game)"}},
                "claims": {"P2339": [{"mainsnak": {"datavalue": {"value": "237182"}}}]},
            }}}),
            http_response(status_code=401),
            http_response(json={"originalimage": {"source": "https://upload.wikimedia.org/root.jpg"}}),
            http_response(content=IMG),
        ], token=None)
        self.assertEqual(result, IMG)
        self.assertEqual(mock_get.call_args_list[4][0][0], "https://upload.wikimedia.org/root.jpg")

    def test_fetch_game_image_fallback_wikidata(self):
        result, mock_get = self._fetch("Terraforming Mars", [
            wikidata_search("Q116278175", "Q36718832"),
            http_response(json={"entities": {
                "Q116278175": {"id": "Q116278175", "labels": {"en": {"value": "Terraforming Mars: Ares Expedition"}}},
                # No label, only the sitelink names it
                "Q36718832": {"id": "Q36718832", "labels": {},
                              "sitelinks": {"enwiki": {"title": "Terraforming Mars (board game)"}}},
            }}),
            http_response(json={"originalimage": {"source": "https://upload.wikimedia.org/tm_box.jpg"},
                                "thumbnail": {"source": "https://upload.wikimedia.org/tm_thumb.jpg"}}),
            http_response(content=IMG),
        ], token=None)
        self.assertEqual(result, IMG)
        self.assertIn("haswbstatement:P2339", mock_get.call_args_list[0].kwargs["params"]["srsearch"])
        self.assertEqual(mock_get.call_args_list[1].kwargs["params"]["ids"], "Q116278175|Q36718832")
        self.assertIn("Terraforming_Mars_%28board_game%29", mock_get.call_args_list[2][0][0])
        self.assertEqual(mock_get.call_args_list[3][0][0], "https://upload.wikimedia.org/tm_box.jpg")

    def test_fetch_game_image_wikidata_commons_image_when_no_article(self):
        result, mock_get = self._fetch("Root", [
            wikidata_search("Q101242941"),
            http_response(json={"entities": {"Q101242941": {"id": "Q101242941", "claims": {
                "P18": [{"mainsnak": {"datavalue": {"value": "Root game box.jpg"}}}],
            }}}}),
            http_response(content=IMG),
        ], token=None)
        self.assertEqual(result, IMG)
        self.assertEqual(mock_get.call_args_list[2][0][0],
                         "https://commons.wikimedia.org/wiki/Special:FilePath/Root_game_box.jpg?width=1000")

    def test_fetch_game_image_fallback_wikipedia_skips_pages_not_about_games(self):
        result, mock_get = self._fetch("Catan", [
            wikidata_search(),
            http_response(json={"query": {"search": [{"title": "Catania"}, {"title": "Catan (film)"}, {"title": "Catan"}]}}),
            http_response(json={"description": "2019 film", "thumbnail": {"source": "https://upload.wikimedia.org/film.jpg"}}),
            http_response(json={"description": "Multiplayer board game",
                                "thumbnail": {"source": "https://upload.wikimedia.org/catan.jpg"}}),
            http_response(content=IMG),
        ], token=None)
        self.assertEqual(result, IMG)
        # 'Catania' is skipped by name without fetching its summary
        self.assertIn("Catan_%28film%29", mock_get.call_args_list[2][0][0])
        self.assertEqual(mock_get.call_args_list[4][0][0], "https://upload.wikimedia.org/catan.jpg")

    def test_fetch_game_image_fallback_bing_verified_by_gemini(self):
        bing_page = (bing_result("https://spam.example/chair.jpg", "Office chair", "https://spam.example/chair")
                     + bing_result("https://shop.example/midgard_bad.jpg", "Champions of Midgard review", "https://blog.example/cm")
                     + bing_result("https://cf.geekdo-images.com/midgard.jpg", "Champions of Midgard",
                                   "https://boardgamegeek.com/boardgame/172287"))
        with patched_config(GEMINI_API_KEY="key"), \
             patch("bot.event_generator.bgg.image_matches_game", side_effect=[False, True]) as verify:
            result, mock_get = self._fetch("Champions of Midgard", [
                wikidata_search(),
                http_response(json={"query": {"search": []}}),
                http_response(text=bing_page),
                http_response(content=b"WRONG" * 300),
                http_response(content=IMG),
            ], token=None)
        self.assertEqual(result, IMG)
        self.assertIn("%22Champions%20of%20Midgard%22%20board%20game", mock_get.call_args_list[2][0][0])
        # The chair is filtered out unseen; the BoardGameGeek page is tried before the blog
        self.assertEqual([c[0][0] for c in mock_get.call_args_list[3:]],
                         ["https://cf.geekdo-images.com/midgard.jpg", "https://shop.example/midgard_bad.jpg"])
        self.assertEqual(verify.call_count, 2)

    def test_fetch_game_image_bing_all_rejected_returns_none(self):
        with patched_config(GEMINI_API_KEY="key"), \
             patch("bot.event_generator.bgg.image_matches_game", return_value=False):
            result, _mock_get = self._fetch("Champions of Midgard", [
                wikidata_search(),
                http_response(json={"query": {"search": []}}),
                http_response(text='<a class="thumb" murl="https://example.com/champions-of-midgard.jpg"></a>'),
                http_response(content=IMG),
            ], token=None)
        self.assertIsNone(result)

    def test_fetch_game_image_bing_skipped_without_gemini_key(self):
        with patched_config(GEMINI_API_KEY=None):
            result, mock_get = self._fetch("Champions of Midgard", [
                wikidata_search(),
                http_response(json={"query": {"search": []}}),
            ], token=None)
        self.assertIsNone(result)
        self.assertEqual(mock_get.call_count, 2)

    def test_fetch_game_image_bgg_error_falls_back_to_web(self):
        result, _mock_get = self._fetch("Monopoly", [
            http_response(status_code=401),
            wikidata_search("Q131457"),
            http_response(json={"entities": {"Q131457": {"id": "Q131457", "sitelinks": {"enwiki": {"title": "Monopoly (game)"}}}}}),
            http_response(json={"thumbnail": {"source": "https://upload.wikimedia.org/mono.jpg"}}),
            http_response(content=IMG),
        ], token="bad_token")
        self.assertEqual(result, IMG)


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

    def test_mentions_game(self):
        self.assertTrue(mentions_game("Heat: Pedal to the Metal", "Heat"))
        self.assertTrue(mentions_game("Root (board game)", "root"))
        self.assertTrue(mentions_game("Go (game)", "Go"))
        self.assertFalse(mentions_game("Lost (TV Series 2004–2010) - IMDb", "Lost Ruins of Arnak"))
        self.assertFalse(mentions_game("Catania", "Catan"))

    def test_bgg_item_matches(self):
        def item(name, alternates=(), subtype="boardgame"):
            return {"name": name, "subtype": subtype, "alternatenames": [{"name": n} for n in alternates]}
        self.assertTrue(bgg_item_matches(item("CATAN"), "Catan"))
        self.assertTrue(bgg_item_matches(item("Heat: Pedal to the Metal"), "Heat"))
        self.assertTrue(bgg_item_matches(item("Dune: Imperium"), "Dune Imperium"))
        self.assertTrue(bgg_item_matches(item("Catan: Seafarers", subtype="boardgameexpansion"), "Catan: Seafarers"))
        self.assertTrue(bgg_item_matches(item("The Lord of the Rings: Duel for Middle-earth",
                                              ["Il Signore degli Anelli: Duello per la Terra di Mezzo"]),
                                         "Il Signore degli Anelli: Duello per la Terra di Mezzo"))
        self.assertFalse(bgg_item_matches(item("Terraforming Mars"), "Terraforming Mars: Ares Expedition"))
        self.assertFalse(bgg_item_matches(item("Vossheim's Holdouts"), "Sky Team"))
        self.assertFalse(bgg_item_matches(item("Catan", subtype="videogame"), "Catan"))

    def test_rank_wikidata_entities(self):
        spin_off = {"id": "Q1", "labels": {"en": {"value": "Catan: Seafarers"}}}
        by_alias = {"id": "Q2", "aliases": {"en": [{"value": "Catan"}]}}
        by_sitelink = {"id": "Q3", "sitelinks": {"itwiki": {"title": "Catan (gioco)"}}}
        self.assertEqual(rank_wikidata_entities([spin_off, by_alias], "catan"), [by_alias, spin_off])
        self.assertEqual(rank_wikidata_entities([spin_off, by_sitelink], "Catan"), [by_sitelink, spin_off])


class TestImageMatchesGame(unittest.TestCase):
    def _verify(self, img=None, answer=None, error=None):
        with patch("bot.event_generator.bgg.generate_from_image", return_value=answer, side_effect=error) as gen:
            return image_matches_game(img or image_bytes(10, 10, fmt="PNG"), "Catan"), gen

    def test_answers(self):
        self.assertTrue(self._verify(answer=" yes.")[0])
        self.assertFalse(self._verify(answer="NO")[0])
        self.assertFalse(self._verify(answer=None)[0])

    def test_sends_detected_mime_type(self):
        _ok, gen = self._verify(answer="YES")
        prompt, _img, mime_type = gen.call_args[0]
        self.assertIn("'Catan'", prompt)
        self.assertEqual(mime_type, "image/png")

    def test_errors_and_unreadable_images_count_as_no(self):
        self.assertFalse(self._verify(error=GeminiQuotaError("429"))[0])
        self.assertFalse(self._verify(error=RuntimeError("boom"))[0])
        ok, gen = self._verify(img=b"<html>not an image</html>", answer="YES")
        self.assertFalse(ok)
        gen.assert_not_called()
        ok, gen = self._verify(img=image_bytes(10, 10, fmt="GIF"), answer="YES")
        self.assertFalse(ok)
        gen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
