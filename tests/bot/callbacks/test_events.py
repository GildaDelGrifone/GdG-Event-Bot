import os
import unittest
from unittest.mock import AsyncMock, patch

import core.db as db
from bot.callbacks.router import handle_callback_query
from tests.support.config import patched_config
from tests.support.db import TempDBMixin, create_event, create_subscribed_event
from tests.support.telegram import callback_update, make_context, make_user

AUDIT_EVENT = dict(
    original_text="Original text", title="Log Test Event", date="10-10-2026", normalized_date="10-10-2026",
    system="D&D", host="GameMaster", seats="1/1", max_seats=1, description="Test description",
)


def _info_messages(mock_logger):
    return [call[0][0] for call in mock_logger.info.call_args_list]


class TestAdminCallbackAuditLogging(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_admin_callback_actions_logging(self):
        event_id = create_event(**AUDIT_EVENT)
        update, query = callback_update(f"discard_event_{event_id}", text=None, caption="Test Caption", photo=[],
                                        user=make_user(998877, "admin_boss"))
        context = make_context()

        with patch("bot.callbacks.events.logger") as mock_logger:
            await handle_callback_query(update, context)
            mock_logger.info.assert_called()
            self.assertTrue(any("998877" in msg and "discarded" in msg for msg in _info_messages(mock_logger)))

        ev_id2 = create_event(**AUDIT_EVENT)

        query.data = f"cancel_event_{ev_id2}"
        with patch("bot.callbacks.events.logger") as mock_logger, \
             patch("bot.callbacks.events.send_cancellation_notice", AsyncMock()), \
             patch("bot.callbacks.events.update_event_messages", AsyncMock()):
            await handle_callback_query(update, context)
            self.assertTrue(any("998877" in msg and "cancelled" in msg for msg in _info_messages(mock_logger)))

        query.data = f"reactivate_event_{ev_id2}"
        with patch("bot.callbacks.events.logger") as mock_logger, \
             patch("bot.callbacks.events.send_reactivation_notice", AsyncMock()), \
             patch("bot.callbacks.events.update_event_messages", AsyncMock()):
            await handle_callback_query(update, context)
            self.assertTrue(any("998877" in msg and "reactivated" in msg for msg in _info_messages(mock_logger)))

        query.data = "discard_recap_10-10-2026"
        with patch("bot.callbacks.recap.logger") as mock_logger:
            await handle_callback_query(update, context)
            self.assertTrue(any("998877" in msg and "discarded recap" in msg for msg in _info_messages(mock_logger)))


class TestDiscardEventCallback(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_discard_event_callback_deletes_event_and_file(self):
        event_id = create_event(original_text="test text", title="Old Event", host="Old Host", description="Old Desc")
        img_file = os.path.join(self.temp_dir.name, "dummy_event.png")
        with open(img_file, "wb") as f:
            f.write(b"dummy")
        db.update_event_field(event_id, "image_path", img_file)
        update, query = callback_update(f"discard_event_{event_id}", text=None, caption="Event Review Message",
                                        photo=True)

        await handle_callback_query(update, make_context())

        self.assertFalse(os.path.exists(img_file))
        self.assertIsNone(db.get_event(event_id))
        query.edit_message_caption.assert_called_once()
        self.assertIn("❌ SCARTATO", query.edit_message_caption.call_args.kwargs.get("caption", ""))


class TestCancelReactivateCallbacks(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_cancel_and_reactivate_callback_flow(self):
        event_id = create_subscribed_event()
        update, query = callback_update(f"cancel_event_{event_id}", text=None, caption="Post evento", photo=True)
        context = make_context()

        def keyboard_callbacks():
            keyboard = query.edit_message_caption.call_args[1]["reply_markup"]
            return [btn.callback_data for row in keyboard.inline_keyboard for btn in row]

        with patched_config(DISCUSSION_GROUP_ID="-100123456"), \
             patch("bot.callbacks.events.update_event_messages", AsyncMock()):
            await handle_callback_query(update, context)
            self.assertEqual(db.get_event(event_id)["status"], "cancelled")
            query.edit_message_caption.assert_called_once()
            self.assertTrue(any("reactivate_event_" in data for data in keyboard_callbacks()))

            query.data = f"reactivate_event_{event_id}"
            query.edit_message_caption.reset_mock()
            await handle_callback_query(update, context)
            self.assertEqual(db.get_event(event_id)["status"], "approved")
            query.edit_message_caption.assert_called_once()
            self.assertTrue(any("cancel_event_" in data for data in keyboard_callbacks()))


if __name__ == "__main__":
    unittest.main()
