import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from core.ai_parser import (
    GeminiQuotaError,
    _apply_seat_safety_net,
    coerce_bool,
    generate_from_image,
    generate_text,
    generate_wordpress_article,
    is_quota_error,
    parse_event_message,
    strip_json_fence,
)

DEPLETED_ERROR = (
    "429 Your prepayment credits are depleted. Please go to AI Studio at https://ai.studio/projects "
    "to manage your project and billing. Learn more at https://ai.google.dev/gemini-api/docs/billing#prepay."
)


@contextmanager
def gemini_returning(text=None, error=None):
    """Patches the Gemini client so models.generate_content returns `text` or raises `error`."""
    with patch("core.ai_parser._gemini_client") as client_factory:
        model = client_factory.return_value.models
        if error is not None:
            model.generate_content.side_effect = error
        else:
            model.generate_content.return_value = MagicMock(text=text)
        yield model


def _fenced_event_json(**fields):
    body = ",\n".join(f'"{k}": {v}' for k, v in fields.items())
    return f"```json\n{{\n{body}\n}}\n```"


class TestGeminiErrors(unittest.TestCase):
    def test_parse_event_message_depleted_credits_raises_quota_error(self):
        with gemini_returning(error=Exception(DEPLETED_ERROR)):
            with self.assertRaises(GeminiQuotaError) as ctx:
                parse_event_message("Test Event text")
        self.assertIn("429", str(ctx.exception))
        self.assertIn("prepayment credits are depleted", str(ctx.exception))

    def test_parse_event_message_other_exception_returns_none(self):
        with gemini_returning(error=ValueError("Syntax or JSON error")):
            self.assertIsNone(parse_event_message("Test Event text"))

    def test_generate_wordpress_article_depleted_credits_raises_quota_error(self):
        with gemini_returning(error=Exception(DEPLETED_ERROR)):
            with self.assertRaises(GeminiQuotaError):
                generate_wordpress_article("Recap text", [])

    def test_generate_text_maps_quota_errors(self):
        with gemini_returning(error=Exception("429 quota exceeded")):
            with self.assertRaises(GeminiQuotaError):
                generate_text("prompt")

    def test_generate_from_image_sends_image_and_maps_quota_errors(self):
        with gemini_returning(text="YES") as model:
            self.assertEqual(generate_from_image("prompt", b"PNGBYTES", "image/png"), "YES")
        image_part, prompt = model.generate_content.call_args.kwargs["contents"]
        self.assertEqual(image_part.inline_data.data, b"PNGBYTES")
        self.assertEqual(image_part.inline_data.mime_type, "image/png")
        self.assertEqual(prompt, "prompt")
        with gemini_returning(error=Exception("RESOURCE_EXHAUSTED")):
            with self.assertRaises(GeminiQuotaError):
                generate_from_image("prompt", b"PNGBYTES")


class TestAiParserHelpers(unittest.TestCase):
    def test_ai_response_helpers(self):
        self.assertEqual(strip_json_fence('```json\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(strip_json_fence(' {"a": 1} '), '{"a": 1}')
        self.assertTrue(is_quota_error(Exception("429 ResourceExhausted")))
        self.assertFalse(is_quota_error(Exception("timeout")))

    def test_seat_safety_net(self):
        data = {"max_seats": 5, "seats": "4/5", "booked_seats": 1}
        _apply_seat_safety_net(data, "Posti liberi: 4/5")
        self.assertEqual(data, {"max_seats": 4, "seats": "4/4", "booked_seats": 0})

        data = {}
        _apply_seat_safety_net(data, "Posti: 0")
        self.assertEqual(data["seats"], "0/0 Completo")

        data = {"seats": "no limit"}
        _apply_seat_safety_net(data, "Nessuna indicazione")
        self.assertEqual(data, {"seats": "no limit"})

    def test_coerce_bool(self):
        self.assertTrue(coerce_bool(" Sì "))
        self.assertFalse(coerce_bool("no"))
        self.assertTrue(coerce_bool(1))
        self.assertFalse(coerce_bool(None))


class TestAiParserRoleplayDetection(unittest.TestCase):
    def test_parse_event_message_extracts_is_roleplay(self):
        response = _fenced_event_json(
            is_event="true", title='"Sine Requie: Terre Perdute"', date='"05-09-2026 21:00"',
            normalized_date='"05-09-2026"', system='"Sine Requie"', host='"Cartomante"', seats='"4/4"',
            max_seats=4, booked_seats=0, is_roleplay="true", extra_info='""', description='"Una terra oscura"',
        )
        with gemini_returning(text=response):
            res = parse_event_message("Test Sine Requie message")
        self.assertIsNotNone(res)
        self.assertTrue(res["is_roleplay"])

    def test_parse_event_message_extracts_is_roleplay_false(self):
        response = _fenced_event_json(
            is_event="true", title='"Arkham Horror LCG"', date='"05-09-2026 21:00"',
            normalized_date='"05-09-2026"', system='"Card Game"', host='"Investigatore"', seats='"3/3"',
            max_seats=3, booked_seats=0, is_roleplay="false", extra_info='""', description='"Campagna Arkham"',
        )
        with gemini_returning(text=response):
            res = parse_event_message("Test Arkham message")
        self.assertIsNotNone(res)
        self.assertFalse(res["is_roleplay"])


if __name__ == "__main__":
    unittest.main()
