import unittest
from unittest.mock import AsyncMock, MagicMock

from bot.common.messages import (
    command_argument,
    edit_card,
    private_chat_link,
    reply_in_chunks,
    send_with_reply_fallback,
    truncate_caption,
    with_html_fallback,
)
from tests.support.telegram import callback_update, make_bot, make_message


class TestSmallHelpers(unittest.TestCase):
    def test_command_argument(self):
        self.assertEqual(command_argument(make_message(text="/ep  hello world ")), "hello world")
        self.assertEqual(command_argument(make_message(caption="/ep")), "")

    def test_truncate_caption(self):
        self.assertEqual(truncate_caption("a" * 1024), "a" * 1024)
        self.assertEqual(truncate_caption("a" * 2000), "a" * 1020 + "...")

    def test_private_chat_link(self):
        self.assertEqual(private_chat_link("-100123", 9, "Admin", "Admin msg"), '<a href="https://t.me/c/123/9">Admin</a>')
        self.assertEqual(private_chat_link("42", 9, "Admin", "Admin msg"), "Admin msg #9")


class TestAsyncHelpers(unittest.IsolatedAsyncioTestCase):
    async def test_with_html_fallback_retries_plain(self):
        send = AsyncMock(side_effect=[Exception("bad markup"), "ok"])
        result = await with_html_fallback(lambda **kw: send(text="x", **kw))
        self.assertEqual(result, "ok")
        self.assertEqual(send.call_args_list[0].kwargs, {"text": "x", "parse_mode": "HTML"})
        self.assertEqual(send.call_args_list[1].kwargs, {"text": "x"})

    async def test_reply_in_chunks_splits_on_limit(self):
        message = make_message()
        await reply_in_chunks(message, ["a" * 6, "b" * 6, "c" * 6], limit=15, prefix="H:", parse_mode="HTML")
        sent = [c.args[0] for c in message.reply_text.call_args_list]
        self.assertEqual(sent, ["H:" + "a" * 6 + "\n", "b" * 6 + "\n" + "c" * 6 + "\n"])
        self.assertTrue(all(c.kwargs == {"parse_mode": "HTML"} for c in message.reply_text.call_args_list))


class TestEditCard(unittest.IsolatedAsyncioTestCase):
    async def test_photo_card_edits_truncated_caption(self):
        _update, query = callback_update("x", text=None, caption="old", photo=True)
        await edit_card(query, "a" * 2000, reply_markup=None)
        query.edit_message_caption.assert_awaited_once_with(caption="a" * 1020 + "...", reply_markup=None)
        query.edit_message_text.assert_not_called()

    async def test_text_card_edits_text(self):
        _update, query = callback_update("x", text="old")
        await edit_card(query, "new", parse_mode="HTML")
        query.edit_message_text.assert_awaited_once_with(text="new", parse_mode="HTML")
        query.edit_message_caption.assert_not_called()


class TestSendWithReplyFallback(unittest.IsolatedAsyncioTestCase):
    async def test_replies_when_possible(self):
        bot = make_bot()
        self.assertTrue(await send_with_reply_fallback(bot, 1, "hi", reply_to_message_id=7))
        self.assertEqual(bot.send_message.call_count, 1)
        self.assertEqual(bot.send_message.call_args.kwargs["reply_to_message_id"], 7)

    async def test_falls_back_to_plain_send(self):
        bot = make_bot()
        bot.send_message.side_effect = [Exception("reply target gone"), None]
        log = MagicMock()
        self.assertTrue(await send_with_reply_fallback(bot, 1, "hi", reply_to_message_id=7, log=log))
        self.assertNotIn("reply_to_message_id", bot.send_message.call_args.kwargs)
        log.warning.assert_called_once()

    async def test_reports_total_failure(self):
        bot = make_bot()
        bot.send_message.side_effect = Exception("down")
        log = MagicMock()
        self.assertFalse(await send_with_reply_fallback(bot, 1, "hi", log=log))
        log.error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
