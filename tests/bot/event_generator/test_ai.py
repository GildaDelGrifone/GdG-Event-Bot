import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from bot.event_generator.ai import (
    _build_prompt, generate_event_data_with_ai, normalize_bgg_ids, normalize_generated_event,
)
from core.ai_parser import GeminiQuotaError


class TestGenerateEventDataWithAi(unittest.TestCase):
    def test_generate_event_data_with_ai_success(self):
        fake_ai_json = {
            "title": "Catan & Wingspan",
            "games": ["Catan", "Wingspan"],
            "date": "Sabato 10-10-2026 21:00",
            "normalized_date": "10-10-2026",
            "system": "Board Game",
            "host": "@Destard",
            "seats": "4/4",
            "max_seats": 4,
            "extra_info": "Adatto a neofiti",
            "is_roleplay": False,
            "description": "Una fantastica serata all'insegna dei giochi da tavolo!",
            "bgg_ids": {"Catan": "13", "Wingspan": None},
        }
        with patch("core.ai_parser._gemini_client") as mock_client:
            mock_client.return_value.models.generate_content.return_value = MagicMock(
                text=f"```json\n{json.dumps(fake_ai_json)}\n```"
            )

            data = generate_event_data_with_ai("Catan e Wingspan sabato 10 ottobre ore 21 host Destard")
            self.assertIsNotNone(data)
            self.assertEqual(data["title"], "Catan & Wingspan")
            self.assertEqual(data["games"], ["Catan", "Wingspan"])
            self.assertEqual(data["booked_seats"], 0)
            self.assertEqual(data["max_seats"], 4)
            self.assertFalse(data["is_roleplay"])
            self.assertEqual(data["bgg_ids"], {"Catan": 13})

    def test_generate_event_data_with_ai_quota_error(self):
        with patch("core.ai_parser._gemini_client") as mock_client:
            mock_client.return_value.models.generate_content.side_effect = Exception("429 Your prepayment credits are depleted")

            with self.assertRaises(GeminiQuotaError):
                generate_event_data_with_ai("prompt")


class TestNormalizeBggIds(unittest.TestCase):
    def test_normalize_bgg_ids(self):
        self.assertEqual(normalize_bgg_ids({"Root": 237182, "Heat": "366013", "X": "abc", "Y": -1, "Z": None}),
                         {"Root": 237182, "Heat": 366013})
        self.assertEqual(normalize_bgg_ids(None), {})
        self.assertEqual(normalize_bgg_ids([13]), {})


if __name__ == "__main__":
    unittest.main()


class TestGeneratedSeats(unittest.TestCase):
    def _normalize(self, prompt, **ai_fields):
        return normalize_generated_event({"title": "Catan", **ai_fields}, prompt)

    def test_seats_in_the_instructions_beat_the_game_player_count(self):
        for prompt in ("Catan venerdì, 6 posti", "Catan venerdì\nPosti: 6", "Catan, posti liberi: 6/8"):
            with self.subTest(prompt=prompt):
                data = self._normalize(prompt, max_seats=4, seats="4/4", booked_seats=2)
                self.assertEqual((data["max_seats"], data["seats"], data["booked_seats"]), (6, "6/6", 0))

    def test_without_seats_in_the_instructions_gemini_value_is_kept_and_made_consistent(self):
        data = self._normalize("Catan venerdì", max_seats=5, seats="4/4")
        self.assertEqual((data["max_seats"], data["seats"]), (5, "5/5"))

        data = self._normalize("Catan venerdì", max_seats="6", seats="6")
        self.assertEqual((data["max_seats"], data["seats"]), (6, "6/6"))

    def test_unlimited_and_full(self):
        for value in (None, "null", "no limit", -3):
            with self.subTest(value=value):
                data = self._normalize("Catan venerdì", max_seats=value, seats="4/4")
                self.assertEqual((data["max_seats"], data["seats"]), (None, "no limit"))

        data = self._normalize("Catan venerdì, 0 posti", max_seats=4)
        self.assertEqual((data["max_seats"], data["seats"]), (0, "0/0 Completo"))

    def test_prompt_states_that_the_instructions_win(self):
        prompt = _build_prompt("Catan 6 posti", datetime(2026, 11, 10))
        self.assertIn("ALWAYS wins", prompt)
        self.assertNotIn('"max_seats": 4', prompt)
