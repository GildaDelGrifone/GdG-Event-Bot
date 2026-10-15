import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import BadRequest, RetryAfter

from bot.service.posts import _execute_with_retry, update_event_messages
from tests.support.config import patched_config
from tests.support.telegram import callback_update, make_context

NOT_MODIFIED = ("Message is not modified: specified new message content and reply markup are exactly the same "
                "as a current content and reply markup of the message")


def channel_event(**overrides):
    """An approved event posted in the channel (photo post unless image_path=None)."""
    return {"id": 1, "title": "Test Event", "date": "2026-10-10", "status": "approved", "telegram_message_id": 123,
            "image_path": "path/to/img.png", **overrides}


def discussion_event(**overrides):
    """An event that only has a booking reply in the discussion group."""
    return {"id": 1, "title": "Test Event", "date": "2026-10-10", "status": "approved", "telegram_message_id": None,
            "discussion_message_id": 999, "discussion_chat_id": -100456, **overrides}


def query_in(chat_id, message_id):
    return callback_update("noop", chat_id=chat_id, message_id=message_id)[1]


class TestExecuteWithRetry(unittest.IsolatedAsyncioTestCase):
    async def test_execute_with_retry_success(self):
        mock_coro = AsyncMock(return_value="done")
        result = await _execute_with_retry(lambda: mock_coro())
        self.assertEqual(result, "done")
        mock_coro.assert_called_once()

    async def test_execute_with_retry_handles_retry_after(self):
        mock_coro = AsyncMock(side_effect=[RetryAfter(0.01), "success"])
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await _execute_with_retry(lambda: mock_coro(), max_retries=2)
            self.assertEqual(result, "success")
            self.assertEqual(mock_coro.call_count, 2)
            mock_sleep.assert_called_once_with(0.01)

    async def test_execute_with_retry_exceeds_max_retries(self):
        mock_coro = AsyncMock(side_effect=RetryAfter(0.01))
        with patch("asyncio.sleep", new_callable=AsyncMock), self.assertRaises(RetryAfter):
            await _execute_with_retry(lambda: mock_coro(), max_retries=2)
        self.assertEqual(mock_coro.call_count, 3)

    async def test_execute_with_retry_raises_other_exception_immediately(self):
        mock_coro = AsyncMock(side_effect=ValueError("other error"))
        with self.assertRaises(ValueError):
            await _execute_with_retry(lambda: mock_coro(), max_retries=2)
        self.assertEqual(mock_coro.call_count, 1)


class TestUpdateChannelPost(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = make_context()
        self.bot = self.context.bot
        config_patch = patched_config(PUBLIC_CHANNEL_ID="-100123")
        config_patch.__enter__()
        self.addCleanup(config_patch.__exit__, None, None, None)

    async def test_update_event_messages_caption_success(self):
        event = channel_event(discussion_message_id=None, discussion_chat_id=None)
        await update_event_messages(self.context, event_id=1, event=event)

        self.bot.edit_message_caption.assert_called_once()
        self.assertEqual(self.bot.edit_message_caption.call_args.kwargs.get("parse_mode"), "HTML")
        self.bot.edit_message_text.assert_not_called()

    async def test_update_event_messages_caption_not_modified_ignored(self):
        self.bot.edit_message_caption.side_effect = BadRequest(NOT_MODIFIED)

        with patch("bot.service.posts.logger") as mock_logger:
            await update_event_messages(self.context, event_id=1, event=channel_event())

        self.bot.edit_message_caption.assert_called_once()
        self.bot.edit_message_text.assert_not_called()
        mock_logger.error.assert_not_called()

    async def test_update_event_messages_caption_fallback_to_text(self):
        self.bot.edit_message_caption.side_effect = BadRequest("Bad Request: there is no caption in the message to edit")

        await update_event_messages(self.context, event_id=1, event=channel_event())

        self.bot.edit_message_caption.assert_called_once()
        self.bot.edit_message_text.assert_called_once()

    async def test_update_event_messages_caption_does_not_fallback_on_unrelated_error(self):
        self.bot.edit_message_caption.side_effect = BadRequest("Bad Request: chat not found")

        with patch("bot.service.posts.logger") as mock_logger:
            await update_event_messages(self.context, event_id=1, event=channel_event())

        self.bot.edit_message_caption.assert_called_once()
        self.bot.edit_message_text.assert_not_called()
        mock_logger.error.assert_called_once()
        self.assertIn("chat not found", str(mock_logger.error.call_args).lower())

    async def test_update_event_messages_text_fallback_to_caption(self):
        self.bot.edit_message_text.side_effect = BadRequest("Bad Request: there is no text in the message to edit")

        await update_event_messages(self.context, event_id=1, event=channel_event(image_path=None))

        self.bot.edit_message_text.assert_called_once()
        self.bot.edit_message_caption.assert_called_once()

    async def test_update_event_messages_text_does_not_fallback_on_unrelated_error(self):
        self.bot.edit_message_text.side_effect = BadRequest("Bad Request: chat not found")

        with patch("bot.service.posts.logger") as mock_logger:
            await update_event_messages(self.context, event_id=1, event=channel_event(image_path=None))

        self.bot.edit_message_text.assert_called_once()
        self.bot.edit_message_caption.assert_not_called()
        mock_logger.error.assert_called_once()

    async def test_update_event_messages_retries_channel_caption_on_flood_control(self):
        self.bot.edit_message_caption.side_effect = [RetryAfter(0.01), MagicMock()]

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await update_event_messages(self.context, event_id=1, event=channel_event())

        self.assertEqual(self.bot.edit_message_caption.call_count, 2)
        mock_sleep.assert_called_once_with(0.01)
        self.bot.edit_message_text.assert_not_called()


class TestUpdateDiscussionReply(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = make_context(bot_username="test_bot")
        self.bot = self.context.bot

    async def test_update_event_messages_discussion_retries_on_flood_control(self):
        self.bot.edit_message_reply_markup.side_effect = [RetryAfter(0.01), MagicMock()]

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await update_event_messages(self.context, event_id=1, event=discussion_event())

        self.assertEqual(self.bot.edit_message_reply_markup.call_count, 2)
        mock_sleep.assert_called_once_with(0.01)

    async def _update_from(self, query, event):
        with patched_config(ADMIN_CHAT_ID="-100999", PUBLIC_CHANNEL_ID="-100123"), \
             patch("bot.service.posts.update_discussion_message_info") as mock_update_db:
            await update_event_messages(self.context, event_id=1, event=event, current_query=query)
        return mock_update_db

    async def test_update_event_messages_admin_chat_query_does_not_strip_admin_card(self):
        admin_query = query_in(-100999, 777)
        mock_update_db = await self._update_from(admin_query, discussion_event(status="cancelled"))

        # Admin query message's markup must NOT be modified
        admin_query.edit_message_reply_markup.assert_not_called()
        mock_update_db.assert_not_called()

        # The actual discussion message must be updated with None (cancelled)
        self.bot.edit_message_reply_markup.assert_called_once_with(chat_id=-100456, message_id=999, reply_markup=None)

    async def test_update_event_messages_reactivate_restores_discussion_buttons(self):
        admin_query = query_in(-100999, 777)
        mock_update_db = await self._update_from(admin_query, discussion_event())

        # Admin query message's markup must NOT be modified
        admin_query.edit_message_reply_markup.assert_not_called()
        mock_update_db.assert_not_called()

        # The actual discussion message must have booking buttons restored
        self.bot.edit_message_reply_markup.assert_called_once()
        call_kwargs = self.bot.edit_message_reply_markup.call_args[1]
        self.assertEqual(call_kwargs["chat_id"], -100456)
        self.assertEqual(call_kwargs["message_id"], 999)
        self.assertIsNotNone(call_kwargs["reply_markup"])

    async def test_update_event_messages_discussion_query_updates_in_place(self):
        disc_query = query_in(-100456, 888)
        mock_update_db = await self._update_from(disc_query, discussion_event())

        # Discussion query message's markup IS updated in place
        disc_query.edit_message_reply_markup.assert_called_once()
        mock_update_db.assert_called_once_with(1, 888, -100456)
        # bot.edit_message_reply_markup is not called because it returned early
        self.bot.edit_message_reply_markup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
