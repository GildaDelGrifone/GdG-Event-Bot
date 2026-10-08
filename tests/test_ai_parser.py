import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import core.db as db
from core import config


class TestGeminiQuotaDepletionAlert(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = self.test_db_path
        db.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()
        config.DB_PATH = self.orig_db_path

    def test_parse_event_message_depleted_credits_raises_quota_error(self):
        from core.ai_parser import parse_event_message, GeminiQuotaError
        err_text = "429 Your prepayment credits are depleted. Please go to AI Studio at https://ai.studio/projects to manage your project and billing. Learn more at https://ai.google.dev/gemini-api/docs/billing#prepay."
        with patch("google.generativeai.GenerativeModel") as mock_model_cls:
            mock_model = MagicMock()
            mock_model.generate_content.side_effect = Exception(err_text)
            mock_model_cls.return_value = mock_model

            with self.assertRaises(GeminiQuotaError) as ctx:
                parse_event_message("Test Event text")
            self.assertIn("429", str(ctx.exception))
            self.assertIn("prepayment credits are depleted", str(ctx.exception))

    def test_parse_event_message_other_exception_returns_none(self):
        from core.ai_parser import parse_event_message
        with patch("google.generativeai.GenerativeModel") as mock_model_cls:
            mock_model = MagicMock()
            mock_model.generate_content.side_effect = ValueError("Syntax or JSON error")
            mock_model_cls.return_value = mock_model

            result = parse_event_message("Test Event text")
            self.assertIsNone(result)

    def test_generate_wordpress_article_depleted_credits_raises_quota_error(self):
        from core.ai_parser import generate_wordpress_article, GeminiQuotaError
        err_text = "429 Your prepayment credits are depleted. Please go to AI Studio at https://ai.studio/projects to manage your project and billing."
        with patch("google.generativeai.GenerativeModel") as mock_model_cls:
            mock_model = MagicMock()
            mock_model.generate_content.side_effect = Exception(err_text)
            mock_model_cls.return_value = mock_model

            with self.assertRaises(GeminiQuotaError):
                generate_wordpress_article("Recap text", [])

    async def test_handle_event_extraction_sends_admin_alert_on_quota_depleted(self):
        from bot.handlers.extraction import handle_event_extraction
        from core.ai_parser import GeminiQuotaError, GEMINI_DEPLETED_ALERT

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        err_text = "429 Your prepayment credits are depleted. Please go to AI Studio at https://ai.studio/projects to manage your project and billing."
        with patch("bot.handlers.extraction.parse_event_message", side_effect=GeminiQuotaError(err_text)), \
             patch("core.config.ADMIN_CHAT_ID", "999"):

            success = await handle_event_extraction(
                text="Titolo: Sessione D&D...",
                image_bytes=None,
                context=context,
                message_link=None,
                telegram_message_id=123
            )

        self.assertFalse(success)
        context.bot.send_message.assert_called_once_with(
            chat_id="999",
            text="🚨 Errore Gemini AI (Crediti esauriti):\n429 Your prepayment credits are depleted."
        )

    async def test_manual_trigger_command_reports_error_when_quota_depleted(self):
        from bot.handlers.ingestion import manual_trigger_command
        from core.ai_parser import GeminiQuotaError

        update = MagicMock()
        update.effective_chat.id = 999
        update.message.reply_to_message = None
        update.message.text = "/ep Sessione di gioco"
        update.message.message_id = 123
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        err_text = "429 Your prepayment credits are depleted."
        with patch("bot.handlers.extraction.parse_event_message", side_effect=GeminiQuotaError(err_text)), \
             patch("core.config.ADMIN_CHAT_ID", "999"):

            await manual_trigger_command(update, context)

        # Context bot sends the quota alert
        context.bot.send_message.assert_called_once_with(
            chat_id="999",
            text="🚨 Errore Gemini AI (Crediti esauriti):\n429 Your prepayment credits are depleted."
        )
        # Update message does NOT send "Processato il testo inviato."
        update.message.reply_text.assert_not_called()

    async def test_recap_approval_sends_admin_alert_on_quota_depleted(self):
        from bot.callbacks.router import handle_callback_query
        from core.ai_parser import GeminiQuotaError

        update = MagicMock()
        query = MagicMock()
        query.data = "publish_recap_05-09-2026"
        query.message.chat_id = 999
        query.message.message_id = 555
        query.message.caption = "Recap caption"
        query.message.text = None
        query.answer = AsyncMock()
        query.edit_message_caption = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query

        context = MagicMock()
        pub_message = MagicMock()
        pub_message.message_id = 777
        context.bot.copy_message = AsyncMock(return_value=pub_message)
        context.bot.send_message = AsyncMock()
        context.bot.send_photo = AsyncMock()

        test_events = [{
            "id": 1,
            "title": "Partita di Prova",
            "date": "05-09-2026",
            "normalized_date": "05-09-2026",
            "system": "D&D",
            "host": "DM",
            "seats": "4/4",
            "booked_seats": 0,
            "max_seats": 4,
            "description": "Descrizione",
            "image_path": None,
            "message_link": "https://t.me/c/123/456",
            "recap": 0
        }]

        err_text = "429 Your prepayment credits are depleted."
        with patch("core.config.PUBLIC_CHANNEL_ID", "-100111111"), \
             patch("bot.callbacks.recap.get_pending_events_for_recap", return_value=test_events), \
             patch("bot.callbacks.recap.generate_wordpress_article", side_effect=GeminiQuotaError(err_text)), \
             patch("bot.callbacks.recap.upload_media", return_value=None), \
             patch("bot.callbacks.recap.create_collage", return_value=None), \
             patch("bot.callbacks.recap.create_recap_story_image", return_value=None):

            await handle_callback_query(update, context)

        # Check that alert was sent to the chat
        found_alert = False
        for call in context.bot.send_message.call_args_list:
            if call.kwargs.get("text") == "🚨 Errore Gemini AI (Crediti esauriti):\n429 Your prepayment credits are depleted.":
                found_alert = True
                break
        self.assertTrue(found_alert, "Expected quota alert message was not sent during recap approval.")



if __name__ == "__main__":
    unittest.main()
