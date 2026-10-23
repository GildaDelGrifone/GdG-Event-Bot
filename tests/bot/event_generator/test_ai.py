import json
import unittest
from unittest.mock import MagicMock, patch

from bot.event_generator.ai import generate_event_data_with_ai, normalize_bgg_ids
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
