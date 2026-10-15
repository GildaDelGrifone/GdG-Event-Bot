import unittest
from unittest.mock import MagicMock, patch

from bot.callbacks.router import handle_callback_query
from bot.handlers.recap import handle_discussion_forward
from bot.state import runtime_state
from core.ai_parser import GeminiQuotaError
from tests.support.config import patched_config
from tests.support.db import TempDBMixin, sample_event
from tests.support.telegram import callback_update, make_context, make_message, make_update


class TestGeminiQuotaDepletionAlert(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_recap_approval_sends_admin_alert_on_quota_depleted(self):
        update, _query = callback_update("publish_recap_05-09-2026", message_id=555, text=None,
                                         caption="Recap caption")
        context = make_context()
        context.bot.copy_message.return_value = MagicMock(message_id=777)

        test_events = [sample_event(
            id=1, title="Partita di Prova", date="05-09-2026", normalized_date="05-09-2026", system="D&D",
            host="DM", description="Descrizione", image_path=None, message_link="https://t.me/c/123/456", recap=0,
        )]

        err_text = "429 Your prepayment credits are depleted."
        with patched_config(PUBLIC_CHANNEL_ID="-100111111"), \
             patch("bot.callbacks.recap.get_pending_events_for_recap", return_value=test_events), \
             patch("bot.callbacks.recap.generate_wordpress_article", side_effect=GeminiQuotaError(err_text)), \
             patch("bot.callbacks.recap.upload_media", return_value=None), \
             patch("bot.callbacks.recap.create_collage", return_value=None), \
             patch("bot.callbacks.recap.create_recap_story_image", return_value=None):
            await handle_callback_query(update, context)

        alert = "🚨 Errore Gemini AI (Crediti esauriti):\n429 Your prepayment credits are depleted."
        found_alert = any(call.kwargs.get("text") == alert for call in context.bot.send_message.call_args_list)
        self.assertTrue(found_alert, "Expected quota alert message was not sent during recap approval.")


class TestPublishRecap(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        saved = (runtime_state.last_recap_message_id, runtime_state.last_recap_events)
        self.addCleanup(lambda: (setattr(runtime_state, "last_recap_message_id", saved[0]),
                                 setattr(runtime_state, "last_recap_events", saved[1])))

    async def test_publish_recap_does_not_send_links_to_event_channel(self):
        update, _query = callback_update("publish_recap_05-09-2026", chat_id=9999, message_id=123, text=None,
                                         caption="Recap caption")
        context = make_context()
        context.bot.copy_message.return_value = MagicMock(message_id=777)

        test_events = [{
            "id": 1,
            "title": "Avventura D&D",
            "system": "D&D 5e",
            "status": "approved",
            "message_link": "https://t.me/c/123/456",
            "image_path": None,
        }]

        with patched_config(PUBLIC_CHANNEL_ID="-100111111"), \
             patch("bot.callbacks.recap.get_pending_events_for_recap", return_value=test_events), \
             patch("bot.callbacks.recap.generate_wordpress_article", return_value=None), \
             patch("bot.callbacks.recap.upload_media", return_value=None), \
             patch("bot.callbacks.recap.create_collage", return_value=None), \
             patch("bot.callbacks.recap.create_recap_story_image", return_value=None):
            await handle_callback_query(update, context)

        # The recap is copied to PUBLIC_CHANNEL_ID
        context.bot.copy_message.assert_called_once_with(chat_id="-100111111", from_chat_id=9999, message_id=123)

        # No second links message is sent to the event channel
        for call in context.bot.send_message.call_args_list:
            self.assertNotEqual(str(call.kwargs.get("chat_id")), "-100111111")

        # The published recap is remembered for the discussion group forward
        self.assertEqual(runtime_state.last_recap_message_id, 777)
        self.assertEqual(runtime_state.last_recap_events, test_events)

        # Telegram automatically forwards the recap post into the discussion group
        fwd_msg = make_message(chat_id=-100222222, message_id=888)
        fwd_msg.is_automatic_forward = True
        fwd_msg.forward_origin = MagicMock(type="channel", message_id=777)

        context.bot.send_message.reset_mock()
        await handle_discussion_forward(make_update(message=fwd_msg), context)

        # The links text is sent to the discussion group instead
        context.bot.send_message.assert_called_once()
        fwd_call = context.bot.send_message.call_args[1]
        self.assertEqual(fwd_call["chat_id"], -100222222)
        self.assertEqual(fwd_call["reply_to_message_id"], 888)
        self.assertIn("<b>Avventura D&amp;D</b>", fwd_call["text"])


if __name__ == "__main__":
    unittest.main()
