import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.common.parsing import UNLIMITED_SEATS_DISPLAY, parse_seats_input
from bot.common.messages import command_argument, private_chat_link, reply_in_chunks, truncate_caption, with_html_fallback
from bot.common.auth import describe_user


class TestParseSeatsInput(unittest.TestCase):
    def test_unlimited_tokens(self):
        for token in ["null", "Nessuno", "illimitati", "unlimited", "none", "0", "", "  "]:
            self.assertIsNone(parse_seats_input(token), token)

    def test_free_over_total(self):
        self.assertEqual(parse_seats_input("2/4"), (2, 4))
        self.assertEqual(parse_seats_input(" 3 / 5 "), (3, 5))

    def test_total_only(self):
        self.assertEqual(parse_seats_input("4"), (None, 4))

    def test_invalid(self):
        for token in ["abc", "x/4", "2/"]:
            with self.assertRaises(ValueError):
                parse_seats_input(token)


class TestSmallHelpers(unittest.TestCase):
    def test_describe_user(self):
        self.assertEqual(describe_user(MagicMock(id=5, username="bob")), "Admin 5 (@bob)")
        self.assertEqual(describe_user(MagicMock(id=5, username=None), role="User"), "User 5")
        self.assertEqual(describe_user(None), "Admin unknown")

    def test_command_argument(self):
        self.assertEqual(command_argument(MagicMock(text="/ep  hello world ", caption=None)), "hello world")
        self.assertEqual(command_argument(MagicMock(text=None, caption="/ep")), "")

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
        message = MagicMock()
        message.reply_text = AsyncMock()
        await reply_in_chunks(message, ["a" * 6, "b" * 6, "c" * 6], limit=15, prefix="H:", parse_mode="HTML")
        sent = [c.args[0] for c in message.reply_text.call_args_list]
        self.assertEqual(sent, ["H:" + "a" * 6 + "\n", "b" * 6 + "\n" + "c" * 6 + "\n"])
        self.assertTrue(all(c.kwargs == {"parse_mode": "HTML"} for c in message.reply_text.call_args_list))


class TestAdminOnlyAndSeatEditing(unittest.IsolatedAsyncioTestCase):
    async def test_admin_only_notify_replies_to_outsiders(self):
        from bot.handlers.repost_schedule import event_schedule_list_command
        update = MagicMock()
        update.effective_chat.id = 999
        update.message.reply_text = AsyncMock()
        with patch("core.config.ADMIN_CHAT_ID", "111"), patch("bot.handlers.repost_schedule.get_all_scheduled_events") as get_all:
            await event_schedule_list_command(update, MagicMock())
        update.message.reply_text.assert_called_once_with("Non sei autorizzato.")
        get_all.assert_not_called()

    async def test_admin_only_silent_for_outsiders(self):
        from bot.handlers.control import bot_status_command
        update = MagicMock()
        update.effective_chat.id = 999
        update.message.reply_text = AsyncMock()
        with patch("core.config.ADMIN_CHAT_ID", "111"):
            await bot_status_command(update, MagicMock())
        update.message.reply_text.assert_not_called()

    async def test_edit_seats_variants(self):
        from bot.handlers.edit import edit_seats, EditInputError
        with patch("bot.handlers.edit.update_event_field", return_value=True) as upd:
            await edit_seats(None, 1, {"booked_seats": 1}, "2/5")
            self.assertEqual(
                [c.args for c in upd.call_args_list],
                [(1, "booked_seats", 3), (1, "max_seats", 5), (1, "seats", "2/5")],
            )

            upd.reset_mock()
            await edit_seats(None, 1, {"booked_seats": 1}, "4")
            self.assertEqual([c.args for c in upd.call_args_list], [(1, "max_seats", 4), (1, "seats", "3/4")])

            upd.reset_mock()
            await edit_seats(None, 1, {}, "null")
            self.assertEqual([c.args for c in upd.call_args_list], [(1, "max_seats", None), (1, "seats", UNLIMITED_SEATS_DISPLAY)])

            with self.assertRaises(EditInputError):
                await edit_seats(None, 1, {}, "tanti")

    def test_extraction_seat_overrides_share_parser(self):
        from bot.handlers.extraction import apply_extraction_overrides
        data = {}
        apply_extraction_overrides(data, override_seats="4")
        self.assertEqual(data, {"max_seats": 4, "seats": "4/4", "booked_seats": 0})

        data = {}
        apply_extraction_overrides(data, override_seats="illimitati")
        self.assertEqual(data, {"max_seats": None, "seats": UNLIMITED_SEATS_DISPLAY, "booked_seats": 0})



class TestSendWithReplyFallback(unittest.IsolatedAsyncioTestCase):
    async def test_replies_when_possible(self):
        from bot.common.messages import send_with_reply_fallback
        bot = MagicMock()
        bot.send_message = AsyncMock()
        self.assertTrue(await send_with_reply_fallback(bot, 1, "hi", reply_to_message_id=7))
        self.assertEqual(bot.send_message.call_count, 1)
        self.assertEqual(bot.send_message.call_args.kwargs["reply_to_message_id"], 7)

    async def test_falls_back_to_plain_send(self):
        from bot.common.messages import send_with_reply_fallback
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=[Exception("reply target gone"), None])
        log = MagicMock()
        self.assertTrue(await send_with_reply_fallback(bot, 1, "hi", reply_to_message_id=7, log=log))
        self.assertNotIn("reply_to_message_id", bot.send_message.call_args.kwargs)
        log.warning.assert_called_once()

    async def test_reports_total_failure(self):
        from bot.common.messages import send_with_reply_fallback
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=Exception("down"))
        log = MagicMock()
        self.assertFalse(await send_with_reply_fallback(bot, 1, "hi", log=log))
        log.error.assert_called_once()


class TestSubscriberTag(unittest.TestCase):
    def test_tag_rules(self):
        from bot.service.mentions import format_subscriber_tag
        self.assertEqual(format_subscriber_tag("@mario"), "@mario")
        self.assertEqual(format_subscriber_tag(None, "Mario <R>", 5), '<a href="tg://user?id=5">Mario &lt;R&gt;</a>')
        self.assertEqual(format_subscriber_tag("Mario Rossi", None, 5), '<a href="tg://user?id=5">Mario Rossi</a>')
        self.assertEqual(format_subscriber_tag(None, None, 5), '<a href="tg://user?id=5">Utente</a>')
        self.assertEqual(format_subscriber_tag(None, "Anna", None), "Anna")
        self.assertIsNone(format_subscriber_tag(None, None, None))

    def test_subscribers_tags_deduplicate(self):
        from bot.callbacks.notices import format_subscribers_tags
        res = [{"username": "Mario"}, {"username": "@mario"}, {"full_name": "Anna"}, {}]
        self.assertEqual(format_subscribers_tags(res), "@Mario, Anna")


class TestCallbackRouter(unittest.IsolatedAsyncioTestCase):
    async def test_dispatches_payload_after_prefix(self):
        import bot.callbacks.router as router
        handler = AsyncMock()
        update = MagicMock()
        update.callback_query.data = "sub_inc_12_34"
        with patch.object(router, "CALLBACK_ROUTES", (("sub_dec_", AsyncMock()), ("sub_inc_", handler))):
            await router.handle_callback_query(update, MagicMock())
        handler.assert_awaited_once()
        self.assertEqual(handler.call_args.args[2], "12_34")

    def test_prefixes_do_not_shadow_each_other(self):
        from bot.callbacks.router import CALLBACK_ROUTES
        prefixes = [p for p, _ in CALLBACK_ROUTES]
        for i, earlier in enumerate(prefixes):
            for later in prefixes[i + 1:]:
                self.assertFalse(later.startswith(earlier), f"{earlier!r} would swallow {later!r}")


class TestEventGeneratorHelpers(unittest.TestCase):
    def test_pick_best_bgg_item(self):
        from bot.event_generator.bgg import pick_best_bgg_item
        items = [{"name": "Catan Sleeves"}, {"name": "Catan: Seafarers"}, {"name": "Catan"}]
        self.assertEqual(pick_best_bgg_item(items, "Catan")["name"], "Catan")
        self.assertEqual(pick_best_bgg_item(items[:2], "catan")["name"], "Catan: Seafarers")
        self.assertEqual(pick_best_bgg_item([{"name": "Dice Bag"}], "x")["name"], "Dice Bag")

    def test_bgg_image_url(self):
        from bot.event_generator.bgg import bgg_image_url
        self.assertEqual(bgg_image_url({"images": {"original": "//cf.geekdo.com/a.jpg"}}), "https://cf.geekdo.com/a.jpg")
        self.assertEqual(bgg_image_url({"imageurl": "https://x/b.jpg"}), "https://x/b.jpg")
        self.assertIsNone(bgg_image_url({}))

    def test_ai_response_helpers(self):
        from core.ai_parser import is_quota_error, strip_json_fence
        self.assertEqual(strip_json_fence('```json\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(strip_json_fence(' {"a": 1} '), '{"a": 1}')
        self.assertTrue(is_quota_error(Exception("429 ResourceExhausted")))
        self.assertFalse(is_quota_error(Exception("timeout")))


class TestScheduleKeyboard(unittest.TestCase):
    def test_active_days_checked_by_key_or_name(self):
        from bot.keyboards import get_schedule_repost_keyboard
        rows = get_schedule_repost_keyboard(3, ["Lunedì", "ven"]).inline_keyboard
        labels = [b.text for b in rows[0] + rows[1]]
        self.assertEqual(labels, ["✅ Lunedì", "⬜ Mercoledì", "✅ Venerdì", "⬜ Sabato", "⬜ Domenica"])
        self.assertEqual(rows[0][0].callback_data, "sched_toggle_3_lun")


if __name__ == "__main__":
    unittest.main()
