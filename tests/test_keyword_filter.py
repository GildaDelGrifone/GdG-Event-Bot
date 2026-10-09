import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.common.parsing import contains_event_keywords
from bot.handlers.extraction import handle_event_extraction


class TestKeywordPreFilter(unittest.IsolatedAsyncioTestCase):
    def test_keywords_with_colon(self):
        # Case insensitive and optional space before colon
        colon_keywords = [
            "Titolo",
            "Posti liberi",
            "Posti",
            "Descrizione",
            "Sinossi",
            "SInossi",
            "Gioco",
            "Quando",
            "Data",
        ]
        for kw in colon_keywords:
            # Without space before colon
            text1 = f"Ecco il post: {kw}: Valore dell'evento"
            self.assertTrue(
                contains_event_keywords(text1),
                f"Failed to match without space: {kw}:"
            )
            # With space before colon
            text2 = f"Ecco il post: {kw} : Valore dell'evento"
            self.assertTrue(
                contains_event_keywords(text2),
                f"Failed to match with space: {kw} :"
            )
            # Lowercase
            text3 = f"{kw.lower()}: valore"
            self.assertTrue(
                contains_event_keywords(text3),
                f"Failed to match lowercase: {kw.lower()}:"
            )
            # Uppercase
            text4 = f"{kw.upper()}: VALORE"
            self.assertTrue(
                contains_event_keywords(text4),
                f"Failed to match uppercase: {kw.upper()}:"
            )

    def test_phrase_keywords(self):
        phrase_keywords = [
            "Gioco da tavolo",
            "Gioco di ruolo",
            "Oneshot",
            "One shot",
            "One-shot",
        ]
        for phrase in phrase_keywords:
            text = f"Venite a provare questo fantastico {phrase} venerdì sera!"
            self.assertTrue(
                contains_event_keywords(text),
                f"Failed to match phrase: {phrase}"
            )
            self.assertTrue(
                contains_event_keywords(text.lower()),
                f"Failed to match lowercase phrase: {phrase.lower()}"
            )
            self.assertTrue(
                contains_event_keywords(text.upper()),
                f"Failed to match uppercase phrase: {phrase.upper()}"
            )

    def test_negative_cases(self):
        non_event_texts = [
            "Avviso importante: domani la sede rimarrà chiusa per festività.",
            "Ricordate di pagare la quota associativa entro fine mese!",
            "Ciao a tutti, ci vediamo presto in associazione.",
            "Numero partecipanti: 4",
            "",
            None,
        ]
        for text in non_event_texts:
            self.assertFalse(
                contains_event_keywords(text),
                f"Should not have matched: {text}"
            )

    async def test_handle_event_extraction_skips_ai_when_keywords_absent(self):
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        text = "Avviso importante: domani la sede rimarrà chiusa per festività."
        with patch("bot.handlers.extraction.parse_event_message") as mock_parse:
            result = await handle_event_extraction(
                text=text,
                image_bytes=None,
                context=context,
                is_manual_trigger=False
            )
            self.assertFalse(result)
            mock_parse.assert_not_called()

    async def test_handle_event_extraction_calls_ai_when_keywords_present(self):
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        text = "Titolo: Torneo di Catan\nQuando: Sabato 15:00\nPosti liberi: 8"
        with patch("bot.handlers.extraction.parse_event_message") as mock_parse, \
             patch("bot.handlers.extraction.insert_event", return_value=1):
            mock_parse.return_value = {
                "is_event": True,
                "title": "Torneo di Catan",
                "date": "Sabato 15:00",
                "normalized_date": "2026-09-12"
            }
            result = await handle_event_extraction(
                text=text,
                image_bytes=None,
                context=context,
                is_manual_trigger=False
            )
            self.assertTrue(result)
            mock_parse.assert_called_once_with(text)

    async def test_handle_event_extraction_manual_trigger_bypasses_keyword_filter(self):
        # When triggered manually via /ep or /event_process, even text without event keywords
        # is processed by the AI parser without being skipped.
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        text = "Testo strano senza keyword esplicite ma che l'admin vuole forzare come evento"
        with patch("bot.handlers.extraction.parse_event_message") as mock_parse, \
             patch("bot.handlers.extraction.insert_event", return_value=1):
            mock_parse.return_value = {
                "is_event": True,
                "title": "Forced Event",
                "date": "Sabato",
                "normalized_date": "2026-09-12"
            }
            result = await handle_event_extraction(
                text=text,
                image_bytes=None,
                context=context,
                is_manual_trigger=True
            )
            self.assertTrue(result)
            mock_parse.assert_called_once_with(text)
