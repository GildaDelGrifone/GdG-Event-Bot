import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import core.db as db
from bot.common.parsing import UNLIMITED_SEATS_DISPLAY
from bot.handlers.extraction import apply_extraction_overrides, handle_event_extraction
from core.ai_parser import GeminiQuotaError
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import make_context

QUOTA_ALERT = "🚨 Errore Gemini AI (Crediti esauriti):\n429 Your prepayment credits are depleted."


class TestKeywordPreFilter(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_handle_event_extraction_skips_ai_when_keywords_absent(self):
        text = "Avviso importante: domani la sede rimarrà chiusa per festività."
        with patch("bot.handlers.extraction.parse_event_message") as mock_parse:
            result = await handle_event_extraction(text=text, image_bytes=None, context=make_context(),
                                                   is_manual_trigger=False)
            self.assertFalse(result)
            mock_parse.assert_not_called()

    async def test_handle_event_extraction_calls_ai_when_keywords_present(self):
        text = "Titolo: Torneo di Catan\nQuando: Sabato 15:00\nPosti liberi: 8"
        parsed = {"is_event": True, "title": "Torneo di Catan", "date": "Sabato 15:00", "normalized_date": "2026-09-12"}
        with patch("bot.handlers.extraction.parse_event_message", return_value=parsed) as mock_parse, \
             patch("bot.handlers.extraction.insert_event", return_value=1):
            result = await handle_event_extraction(text=text, image_bytes=None, context=make_context(),
                                                   is_manual_trigger=False)
            self.assertTrue(result)
            mock_parse.assert_called_once_with(text)

    async def test_handle_event_extraction_manual_trigger_bypasses_keyword_filter(self):
        # /ep and /event_process run the AI parser even when the text has no event keywords
        text = "Testo strano senza keyword esplicite ma che l'admin vuole forzare come evento"
        parsed = {"is_event": True, "title": "Forced Event", "date": "Sabato", "normalized_date": "2026-09-12"}
        with patch("bot.handlers.extraction.parse_event_message", return_value=parsed) as mock_parse, \
             patch("bot.handlers.extraction.insert_event", return_value=1):
            result = await handle_event_extraction(text=text, image_bytes=None, context=make_context(),
                                                   is_manual_trigger=True)
            self.assertTrue(result)
            mock_parse.assert_called_once_with(text)


class TestGeminiQuotaDepletionAlert(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_handle_event_extraction_sends_admin_alert_on_quota_depleted(self):
        context = make_context()
        err_text = ("429 Your prepayment credits are depleted. Please go to AI Studio at "
                    "https://ai.studio/projects to manage your project and billing.")
        with patch("bot.handlers.extraction.parse_event_message", side_effect=GeminiQuotaError(err_text)), \
             as_admin_chat():
            success = await handle_event_extraction(
                text="Titolo: Sessione D&D...",
                image_bytes=None,
                context=context,
                message_link=None,
                telegram_message_id=123,
            )

        self.assertFalse(success)
        context.bot.send_message.assert_called_once_with(chat_id="999", text=QUOTA_ALERT)


class TestDateAnomalyWarnings(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def _extract_on_2026_09_01(self, parsed, text):
        """Runs a manual extraction of `parsed` with today pinned to 01-09-2026; returns the bot's send_message mock."""
        context = make_context()
        with patch("bot.handlers.extraction.parse_event_message", return_value=parsed), \
             as_admin_chat(), \
             patch("utils.date_utils.date") as mock_date:
            mock_date.today.return_value = date(2026, 9, 1)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            await handle_event_extraction(text=text, image_bytes=None, context=context, is_manual_trigger=True)
        return context.bot.send_message

    async def test_handle_event_extraction_past_date_warning_shown(self):
        send_message = await self._extract_on_2026_09_01({
            "is_event": True, "title": "Vecchio Evento", "date": "01-01-2024", "normalized_date": "01-01-2024",
            "system": "OSR", "host": "Old Master", "seats": "3/3", "max_seats": 3,
        }, "Evento 01-01-2024")

        send_message.assert_called_once()
        sent_text = send_message.call_args.kwargs.get("text", "")
        self.assertIn("🚨 ATTENZIONE ANOMALIE DATA:", sent_text)
        self.assertIn("PASSATO", sent_text)

    async def test_handle_event_extraction_weekday_mismatch_warning_shown(self):
        # Sept 4, 2026 is Friday, but the date says "Sabato 04-09-2026"
        send_message = await self._extract_on_2026_09_01({
            "is_event": True, "title": "Evento Sabato", "date": "Sabato 04-09-2026", "normalized_date": "04-09-2026",
            "system": "OSR", "host": "Master", "seats": "3/3", "max_seats": 3,
        }, "Evento Sabato 04-09-2026")

        send_message.assert_called_once()
        sent_text = send_message.call_args.kwargs.get("text", "")
        self.assertIn("🚨 ATTENZIONE ANOMALIE DATA:", sent_text)
        self.assertIn("Incongruenza data/giorno", sent_text)
        self.assertIn("Sabato", sent_text)
        self.assertIn("Venerdì", sent_text)


class TestAdminCardFormatting(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        # An existing event, so the extracted one gets id self.event_id + 1
        self.event_id = create_event(original_text="test text", title="Old Event", host="Old Host",
                                     description="Old Desc")

    async def test_handle_event_extraction_uses_final_form_with_emojis(self):
        context = make_context()
        context.bot.send_message.return_value = MagicMock(message_id=777)
        parsed_data = {
            "is_event": True,
            "title": "Avventura Stellare",
            "date": "Venerdì 25-12-2026 21:00",
            "normalized_date": "25-12-2026",
            "system": "Starfinder",
            "host": "Capitano",
            "seats": "5/5",
            "booked_seats": 0,
            "max_seats": 5,
            "description": "Viaggio nello spazio profondo.",
            "is_roleplay": True,
        }

        with patch("bot.handlers.extraction.parse_event_message", return_value=parsed_data), as_admin_chat():
            success = await handle_event_extraction(text="Evento Starfinder", image_bytes=None, context=context,
                                                    is_manual_trigger=True)

        self.assertTrue(success)
        context.bot.send_message.assert_called_once()
        sent_kwargs = context.bot.send_message.call_args.kwargs
        text = sent_kwargs.get("text", "")

        self.assertIn("📣 <b>Avventura Stellare</b>", text)
        self.assertIn("🎲 Sistema: Starfinder", text)
        self.assertIn("👑 Master: Capitano", text)
        self.assertIn("🪑 Posti: 5/5", text)
        self.assertEqual(sent_kwargs.get("parse_mode"), "HTML")

        # admin_message_id was stored in the DB
        self.assertEqual(db.get_event(self.event_id + 1).get("admin_message_id"), 777)

    async def test_handle_event_extraction_warns_on_caption_over_1024_chars(self):
        context = make_context()
        context.bot.send_photo.return_value = MagicMock(message_id=888)
        parsed_data = {
            "is_event": True,
            "title": "Evento Lunghissimo",
            "date": "Venerdì 25-12-2026 21:00",
            "normalized_date": "25-12-2026",
            "system": "D&D",
            "host": "Master",
            "seats": "4/4",
            "booked_seats": 0,
            "max_seats": 4,
            "description": "X" * 1100,
        }

        with patch("bot.handlers.extraction.parse_event_message", return_value=parsed_data), as_admin_chat():
            success = await handle_event_extraction(text="Evento con testo lunghissimo", image_bytes=b"dummy_image_data",
                                                    context=context, is_manual_trigger=True)

        self.assertTrue(success)
        context.bot.send_photo.assert_called_once()
        caption = context.bot.send_photo.call_args.kwargs.get("caption", "")

        self.assertIn("🚨 ATTENZIONE LIMITE CARATTERI:", caption)
        self.assertIn("IL TESTO DELL'EVENTO SUPERA I 1024 CARATTERI", caption)
        self.assertLessEqual(len(caption), 1024)


class TestExtractionOverrides(unittest.TestCase):
    def test_extraction_seat_overrides_share_parser(self):
        data = {}
        apply_extraction_overrides(data, override_seats="4")
        self.assertEqual(data, {"max_seats": 4, "seats": "4/4", "booked_seats": 0})

        data = {}
        apply_extraction_overrides(data, override_seats="illimitati")
        self.assertEqual(data, {"max_seats": None, "seats": UNLIMITED_SEATS_DISPLAY, "booked_seats": 0})


if __name__ == "__main__":
    unittest.main()
