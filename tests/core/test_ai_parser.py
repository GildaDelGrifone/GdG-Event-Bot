import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from core.ai_parser import (
    GeminiQuotaError,
    _apply_seat_safety_net,
    coerce_bool,
    generate_from_image,
    generate_astro_article,
    generate_text,
    strip_code_fence,
    _article_prompt,
    _astro_article_prompt,
    generate_wordpress_article,
    is_quota_error,
    parse_event_message,
    strip_json_fence,
)
from tests.support.config import patched_config

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


class TestAstroArticle(unittest.TestCase):
    EVENTS = [{"title": "Catan", "message_link": "https://t.me/c/1/2", "media_url": "https://r2/serate/x/catan.jpg"}]

    def test_markdown_fence_is_stripped_and_image_url_is_kept(self):
        article = "### Catan\n\n![Catan](https://r2/serate/x/catan.jpg)\n\nTesto"
        with gemini_returning(f"```markdown\n{article}\n```") as model:
            self.assertEqual(generate_astro_article("Recap", self.EVENTS), article)
        prompt = model.generate_content.call_args.kwargs["contents"]
        self.assertIn("Image URL: https://r2/serate/x/catan.jpg", prompt)
        self.assertIn("Markdown", prompt)
        self.assertNotIn("<img", prompt)

    def test_prompt_prescribes_the_layout_of_the_older_articles(self):
        with patched_config(EVENT_START_TIME="20:45"):
            prompt = _astro_article_prompt("Recap", self.EVENTS)

        self.assertIn("one plain paragraph with NO heading", prompt)
        self.assertIn("One section for EACH event", prompt)
        self.assertIn("Never merge or group events", prompt)
        self.assertIn("a cancelled event gets its own section too", prompt)
        self.assertIn("**annullato**", prompt)
        self.assertIn("never as a bare URL", prompt)
        self.assertIn("**@name** ([https://t.me/name](https://t.me/name))", prompt)
        self.assertIn("l'utente Telegram **@Destard** ([https://t.me/Destard](https://t.me/Destard))", prompt)
        self.assertNotIn("@Destard (https://t.me/Destard)", prompt)
        self.assertIn("do not list them again", prompt)
        self.assertIn("a line containing only ---", prompt)
        self.assertIn('"Vi aspettiamo in sede alle **20:45**"', prompt)
        self.assertLess(prompt.index("![<Event title>]"), prompt.index("[<Short call to action"))
        self.assertIn("after the text and before the link", prompt)
        self.assertNotIn("<img", prompt)

    def test_unfenced_markdown_is_returned_as_is(self):
        with gemini_returning("  ### Titolo\n\nTesto  "):
            self.assertEqual(generate_astro_article("Recap", []), "### Titolo\n\nTesto")

    def test_quota_error_is_reraised_and_other_errors_return_none(self):
        with gemini_returning(error=Exception(DEPLETED_ERROR)):
            with self.assertRaises(GeminiQuotaError):
                generate_astro_article("Recap", [])
        with gemini_returning(error=Exception("boom")):
            self.assertIsNone(generate_astro_article("Recap", []))

    def test_strip_code_fence_handles_any_language_tag(self):
        self.assertEqual(strip_code_fence("```md\nx\n```"), "x")
        self.assertEqual(strip_code_fence("```\nx\n```"), "x")
        self.assertEqual(strip_code_fence("a ```b``` c"), "a ```b``` c")

    def test_html_prompt_is_unchanged_and_uses_wp_media_url(self):
        prompt = _article_prompt("Recap", [{"title": "T", "message_link": "L", "wp_media_url": "U"}])
        self.assertIn("Image URL: U", prompt)
        self.assertIn("<img src=", prompt)
        self.assertIn("Return the response as HTML", prompt)


if __name__ == "__main__":
    unittest.main()
