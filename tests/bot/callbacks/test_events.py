import os
import unittest
from unittest.mock import AsyncMock, patch

from telegram.error import Forbidden

import core.db as db
from bot.callbacks.router import handle_callback_query
from bot.service.deletion import DeletionResult
from bot.state import runtime_state
from tests.support.config import eventbrite_credentials, patched_config
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

        query.data = f"cancel_confirm_{ev_id2}"
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
    async def test_discard_keeps_event_reservations_and_image(self):
        event_id = create_event(original_text="test text", title="Old Event", host="Old Host", description="Old Desc")
        db.admin_add_subscriber(event_id, "mario")
        img_file = os.path.join(self.temp_dir.name, "dummy_event.png")
        with open(img_file, "wb") as f:
            f.write(b"dummy")
        db.update_event_field(event_id, "image_path", img_file)
        update, query = callback_update(f"discard_event_{event_id}", text=None, caption="Event Review Message",
                                        photo=True)

        await handle_callback_query(update, make_context())

        self.assertTrue(os.path.exists(img_file))
        event = db.get_event(event_id)
        self.assertEqual(event["status"], "discarded")
        self.assertIsNotNone(event["discarded_at"])
        self.assertEqual(len(db.get_reservations_for_event(event_id)), 1)
        kwargs = query.edit_message_caption.call_args.kwargs
        self.assertIn("❌ SCARTATO", kwargs.get("caption", ""))
        self.assertEqual(kwargs["reply_markup"].inline_keyboard[0][0].callback_data, f"restore_event_{event_id}")

    async def test_restore_puts_the_event_back_to_pending(self):
        event_id = create_event()
        db.discard_event(event_id)
        update, query = callback_update(f"restore_event_{event_id}", text=None,
                                        caption="Card\n\n❌ SCARTATO", photo=True)
        await handle_callback_query(update, make_context())
        event = db.get_event(event_id)
        self.assertEqual(event["status"], "pending")
        self.assertIsNone(event["discarded_at"])
        kwargs = query.edit_message_caption.call_args.kwargs
        self.assertEqual(kwargs["caption"], "Card")
        self.assertEqual(kwargs["reply_markup"].inline_keyboard[0][0].callback_data, f"publish_event_{event_id}")

    async def test_restore_extracts_an_image_the_nightly_job_zipped(self):
        import zipfile
        event_id = create_event()
        img_file = os.path.join(self.temp_dir.name, "event_x.jpg")
        with zipfile.ZipFile(os.path.join(self.temp_dir.name, "archive.zip"), "w") as archive:
            archive.writestr("event_x.jpg", b"jpeg")
        db.update_event_field(event_id, "image_path", img_file)
        db.discard_event(event_id)
        update, query = callback_update(f"restore_event_{event_id}", text=None, caption="Card", photo=True)
        await handle_callback_query(update, make_context())
        with open(img_file, "rb") as f:
            self.assertEqual(f.read(), b"jpeg")
        self.assertEqual(query.answer.call_args.args[0], "Evento ripristinato: è di nuovo in attesa di approvazione.")

    async def test_restore_of_a_purged_event_says_so(self):
        update, query = callback_update("restore_event_999", text=None, caption="Card", photo=True)
        await handle_callback_query(update, make_context())
        self.assertIn("eliminato definitivamente", query.answer.call_args.args[0])

    async def test_restore_on_an_event_that_is_not_discarded_is_refused(self):
        event_id = create_event(status="approved")
        update, query = callback_update(f"restore_event_{event_id}", text=None, caption="Card", photo=True)
        await handle_callback_query(update, make_context())
        self.assertEqual(db.get_event(event_id)["status"], "approved")
        self.assertIn("già pubblicato", query.answer.call_args.args[0])

    async def test_publish_on_a_discarded_card_is_refused(self):
        event_id = create_event()
        db.discard_event(event_id)
        update, query = callback_update(f"publish_event_{event_id}", text=None, caption="Card", photo=True)
        with patch("bot.callbacks.events._publish_to_channel", new_callable=AsyncMock) as post:
            await handle_callback_query(update, make_context())
        post.assert_not_awaited()
        self.assertIn("scartato", query.answer.call_args.args[0])
        self.assertIn("❌ SCARTATO", query.edit_message_caption.call_args.kwargs["caption"])


class TestCancelReactivateCallbacks(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_cancel_and_reactivate_callback_flow(self):
        event_id = create_subscribed_event()
        update, query = callback_update(f"cancel_confirm_{event_id}", text=None, caption="Post evento", photo=True)
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


class TestEventbriteCallbacks(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.context = make_context()
        self.publish = patch("bot.callbacks.events.start_eventbrite_publish", new_callable=AsyncMock).start()
        self.cancel = patch("bot.callbacks.events.cancel_on_eventbrite", new_callable=AsyncMock).start()
        self.reactivate = patch("bot.callbacks.events.reactivate_on_eventbrite", new_callable=AsyncMock).start()
        self.recreate = self.publish
        self.update_messages = patch("bot.callbacks.events.update_event_messages", new_callable=AsyncMock).start()
        patch("bot.callbacks.events.send_cancellation_notice", new_callable=AsyncMock).start()
        patch("bot.callbacks.events.send_reactivation_notice", new_callable=AsyncMock).start()
        self.story = patch("bot.callbacks.events._send_story_preview", new_callable=AsyncMock).start()
        self.addCleanup(patch.stopall)

    async def test_publish_with_eventbrite_publishes_on_telegram_then_on_eventbrite(self):
        event_id = create_event()
        update, query = callback_update(f"publish_eb_event_{event_id}", chat_id=999, text=None, caption="Card", photo=True)

        with patched_config(PUBLIC_CHANNEL_ID=None):
            await handle_callback_query(update, self.context)

        self.assertEqual(db.get_event(event_id)["status"], "approved")
        query.edit_message_caption.assert_called_once()
        self.assertIn("✅ APPROVATO", query.edit_message_caption.call_args.kwargs["caption"])
        self.publish.assert_awaited_once_with(self.context, event_id, 999)

    async def test_solo_eventbrite_button_approves_without_a_channel_post_and_publishes_on_eventbrite(self):
        event_id = create_event()
        update, query = callback_update(f"publish_eb_only_{event_id}", chat_id=999, text=None, caption="Card", photo=True)
        with patched_config(PUBLIC_CHANNEL_ID="-100500"):
            await handle_callback_query(update, self.context)

        event = db.get_event(event_id)
        self.assertEqual(event["status"], "approved")
        self.assertIsNone(event["telegram_message_id"])
        channels = [c for c in self.context.bot.send_message.call_args_list if c.kwargs["chat_id"] == "-100500"]
        self.assertEqual(channels, [])
        self.context.bot.send_photo.assert_not_called()
        self.assertIn("senza pubblicazione su Telegram", self.context.bot.send_message.call_args.kwargs["text"])
        self.publish.assert_awaited_once_with(self.context, event_id, 999)

    async def test_eventbrite_only_mode_still_posts_telegram_plus_eb_but_makes_no_story(self):
        event_id = create_event()
        update, _ = callback_update(f"publish_eb_event_{event_id}", chat_id=999, text=None, caption="Card", photo=True)
        with patched_config(PUBLIC_CHANNEL_ID="-100500"), patch.object(runtime_state, "eventbrite_only", True), \
                patch("bot.callbacks.events._publish_to_channel", new_callable=AsyncMock) as post:
            await handle_callback_query(update, self.context)

        post.assert_awaited_once()
        self.story.assert_not_awaited()
        self.publish.assert_awaited_once()

    async def test_story_is_generated_outside_eventbrite_only_mode(self):
        event_id = create_event()
        update, _ = callback_update(f"publish_event_{event_id}", chat_id=999, text=None, caption="Card", photo=True)
        with patched_config(PUBLIC_CHANNEL_ID=None), patch.object(runtime_state, "eventbrite_only", False):
            await handle_callback_query(update, self.context)
        self.story.assert_awaited_once()

    async def test_plain_publish_never_touches_eventbrite(self):
        event_id = create_event()
        update, _ = callback_update(f"publish_event_{event_id}", chat_id=999, text=None, caption="Card", photo=True)
        with patched_config(PUBLIC_CHANNEL_ID=None):
            await handle_callback_query(update, self.context)
        self.assertEqual(db.get_event(event_id)["status"], "approved")
        self.publish.assert_not_awaited()

    async def test_eventbrite_publish_button(self):
        event_id = create_event(status="approved")
        update, query = callback_update(f"eb_publish_{event_id}", chat_id=999)
        await handle_callback_query(update, self.context)
        query.answer.assert_awaited()
        self.publish.assert_awaited_once_with(self.context, event_id, 999)

    async def test_recreate_button_is_removed_and_recreates(self):
        event_id = create_event(status="approved")
        update, query = callback_update(f"eb_recreate_{event_id}", chat_id=999)
        await handle_callback_query(update, self.context)
        query.edit_message_reply_markup.assert_awaited_once_with(reply_markup=None)
        self.recreate.assert_awaited_once_with(self.context, event_id, 999, recreate=True)

    async def test_cancel_and_reactivate_mirror_on_eventbrite_only_for_linked_events(self):
        linked = create_event(status="approved")
        db.set_eventbrite_info(linked, eventbrite_event_id="eb1", eventbrite_status="live")
        unlinked = create_event(status="approved")

        for event_id in (linked, unlinked):
            update, _ = callback_update(f"cancel_confirm_{event_id}", text=None, caption="Card", photo=True)
            await handle_callback_query(update, self.context)
        self.cancel.assert_awaited_once()
        cancelled_event = self.cancel.call_args.args[1]
        self.assertEqual((cancelled_event["id"], cancelled_event["status"]), (linked, "cancelled"))

        for event_id in (linked, unlinked):
            update, _ = callback_update(f"reactivate_event_{event_id}", text=None, caption="Card", photo=True)
            await handle_callback_query(update, self.context)
        self.reactivate.assert_awaited_once()
        reactivated_event = self.reactivate.call_args.args[1]
        self.assertEqual((reactivated_event["id"], reactivated_event["status"]), (linked, "approved"))

    async def test_reactivated_card_shows_the_eventbrite_dashboard_button(self):
        event_id = create_event(status="cancelled")
        db.set_eventbrite_info(event_id, eventbrite_event_id="eb1", eventbrite_status="unpublished")
        update, query = callback_update(f"reactivate_event_{event_id}", text=None, caption="Card", photo=True)

        with eventbrite_credentials():
            await handle_callback_query(update, self.context)

        keyboard = query.edit_message_caption.call_args.kwargs["reply_markup"]
        urls = [b.url for row in keyboard.inline_keyboard for b in row if b.url]
        self.assertEqual(urls, ["https://www.eventbrite.com/events/eb1/dashboard/?eid=eb1"])


class TestCancelConfirmation(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.context = make_context()
        self.cancel_eb = patch("bot.callbacks.events.cancel_on_eventbrite", new_callable=AsyncMock).start()
        self.update_messages = patch("bot.callbacks.events.update_event_messages", new_callable=AsyncMock).start()
        self.notice = patch("bot.callbacks.events.send_cancellation_notice", new_callable=AsyncMock).start()
        self.addCleanup(patch.stopall)

    def buttons(self, query):
        keyboard = query.edit_message_reply_markup.call_args.kwargs["reply_markup"]
        return [(b.text, b.callback_data) for row in keyboard.inline_keyboard for b in row]

    async def test_cancel_button_only_asks_for_confirmation(self):
        event_id = create_subscribed_event()  # 2 Telegram seats booked
        update, query = callback_update(f"cancel_event_{event_id}", text=None, caption="Card", photo=True)

        await handle_callback_query(update, self.context)

        self.assertEqual(db.get_event(event_id)["status"], "approved")
        self.assertEqual(self.buttons(query), [("✅ Sì, annulla", f"cancel_confirm_{event_id}"),
                                              ("↩️ Indietro", f"cancel_abort_{event_id}")])
        query.answer.assert_awaited_once_with()  # no popup: the confirmation buttons are the warning
        query.edit_message_caption.assert_not_called()
        self.cancel_eb.assert_not_awaited()
        self.update_messages.assert_not_awaited()
        self.notice.assert_not_awaited()

    async def test_unknown_event(self):
        update, query = callback_update("cancel_event_999", text=None, caption="Card", photo=True)
        await handle_callback_query(update, self.context)
        query.answer.assert_awaited_with("Evento non trovato.", show_alert=True)
        query.edit_message_reply_markup.assert_not_called()

    async def test_abort_restores_the_card_buttons_and_changes_nothing(self):
        event_id = create_event(status="approved")
        update, query = callback_update(f"cancel_abort_{event_id}", text=None, caption="Card", photo=True)

        await handle_callback_query(update, self.context)

        self.assertEqual(db.get_event(event_id)["status"], "approved")
        callbacks = [data for _, data in self.buttons(query)]
        self.assertIn(f"cancel_event_{event_id}", callbacks)
        self.assertNotIn(f"cancel_confirm_{event_id}", callbacks)
        self.cancel_eb.assert_not_awaited()

    async def test_confirm_cancels_and_a_repeated_confirm_does_nothing(self):
        event_id = create_subscribed_event()
        update, query = callback_update(f"cancel_confirm_{event_id}", text=None, caption="Card", photo=True)

        with patched_config(DISCUSSION_GROUP_ID="-100123456"):
            await handle_callback_query(update, self.context)
            self.assertEqual(db.get_event(event_id)["status"], "cancelled")
            self.notice.assert_awaited_once()
            self.update_messages.assert_awaited_once()

            query.answer.reset_mock()
            await handle_callback_query(update, self.context)

        query.answer.assert_awaited_with("Evento già annullato.")
        self.notice.assert_awaited_once()  # no second notice to the subscribers

    async def test_confirm_mirrors_on_eventbrite_only_for_linked_events(self):
        linked = create_event(status="approved")
        db.set_eventbrite_info(linked, eventbrite_event_id="eb1", eventbrite_status="live")
        plain = create_event(status="approved")
        for event_id in (linked, plain):
            update, _ = callback_update(f"cancel_confirm_{event_id}", text=None, caption="Card", photo=True)
            await handle_callback_query(update, self.context)
        self.cancel_eb.assert_awaited_once()
        self.assertEqual(self.cancel_eb.call_args.args[1]["id"], linked)

    async def test_the_confirm_prompt_is_only_one_press_away_from_the_old_behaviour(self):
        from bot.keyboards import get_approved_event_keyboard
        event_id = create_event(status="approved")
        callbacks = [b.callback_data for row in get_approved_event_keyboard(event_id).inline_keyboard for b in row]
        self.assertIn(f"cancel_event_{event_id}", callbacks)
        self.assertNotIn(f"cancel_confirm_{event_id}", callbacks)  # the approved card never cancels directly


class TestEventbriteCancelRetry(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_retry_button_completes_the_cancellation(self):
        event_id = create_event(status="cancelled")
        context = make_context()
        update, query = callback_update(f"eb_cancel_retry_{event_id}", chat_id=999)
        with patch("bot.callbacks.events.finish_eventbrite_cancellation", new_callable=AsyncMock) as finish:
            await handle_callback_query(update, context)
        finish.assert_awaited_once()
        self.assertEqual(finish.call_args.args[1]["id"], event_id)
        self.assertEqual(finish.call_args.args[2], 999)

    async def test_the_links_message_is_passed_as_temporary(self):
        event_id = create_event(status="cancelled")
        update, query = callback_update(f"eb_cancel_retry_{event_id}", chat_id=999, message_id=123)
        with patch("bot.callbacks.events.finish_eventbrite_cancellation", new_callable=AsyncMock) as finish:
            await handle_callback_query(update, make_context())
        self.assertIs(finish.call_args.kwargs["temporary_message"], query.message)

    async def test_the_admin_card_itself_is_never_deleted(self):
        event_id = create_event(status="cancelled")
        update, query = callback_update(f"eb_cancel_retry_{event_id}", chat_id=999, message_id=123)
        with patch("bot.callbacks.events.get_event", return_value={"id": event_id, "admin_message_id": 123}), \
                patch("bot.callbacks.events.finish_eventbrite_cancellation", new_callable=AsyncMock) as finish:
            await handle_callback_query(update, make_context())
        self.assertIsNone(finish.call_args.kwargs["temporary_message"])

    async def test_unknown_event(self):
        update, query = callback_update("eb_cancel_retry_999", chat_id=999)
        with patch("bot.callbacks.events.finish_eventbrite_cancellation", new_callable=AsyncMock) as finish:
            await handle_callback_query(update, make_context())
        finish.assert_not_awaited()
        query.answer.assert_awaited_with("Evento non trovato.", show_alert=True)


class TestEventbriteOnlyCancelCallbacks(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.context = make_context()
        self.cancel_only = patch("bot.callbacks.events.cancel_only_on_eventbrite", new_callable=AsyncMock).start()
        self.cancel_telegram = patch("bot.callbacks.events.send_cancellation_notice", new_callable=AsyncMock).start()
        self.addCleanup(patch.stopall)

    def linked(self, status="approved", eb_status="live"):
        event_id = create_event(status=status)
        db.set_eventbrite_info(event_id, eventbrite_event_id="eb1", eventbrite_status=eb_status)
        return event_id

    async def test_ask_only_swaps_in_the_confirmation(self):
        event_id = self.linked()
        db.apply_eventbrite_order(event_id, "o1", "Mario R.", 2)
        update, query = callback_update(f"eb_cancel_ask_{event_id}", chat_id=999)

        await handle_callback_query(update, self.context)

        query.answer.assert_awaited_once_with()  # no popup: the confirmation buttons are the warning
        keyboard = query.edit_message_reply_markup.call_args.kwargs["reply_markup"]
        self.assertEqual([(b.text, b.callback_data) for b in keyboard.inline_keyboard[0]], [
            ("✅ Sì, annulla su EB", f"eb_cancel_do_{event_id}"),
            ("↩️ Indietro", f"cancel_abort_{event_id}"),
        ])
        self.cancel_only.assert_not_awaited()

    async def test_confirm_cancels_on_eventbrite_only(self):
        event_id = self.linked()
        update, query = callback_update(f"eb_cancel_do_{event_id}", chat_id=999)

        await handle_callback_query(update, self.context)

        self.cancel_only.assert_awaited_once()
        self.assertEqual(self.cancel_only.call_args.args[1]["id"], event_id)
        self.assertEqual(self.cancel_only.call_args.args[2], 999)
        self.assertEqual(db.get_event(event_id)["status"], "approved")
        self.cancel_telegram.assert_not_awaited()

    async def test_refused_when_there_is_nothing_to_cancel(self):
        cases = [self.linked(eb_status="canceled"), self.linked(eb_status="closed"), self.linked(eb_status="draft"),
                 self.linked(status="cancelled"), create_event(status="approved"), 999]
        for event_id in cases:
            for prefix in ("eb_cancel_ask_", "eb_cancel_do_"):
                with self.subTest(event_id=event_id, prefix=prefix):
                    update, query = callback_update(f"{prefix}{event_id}", chat_id=999)
                    await handle_callback_query(update, self.context)
                    query.answer.assert_awaited_with("Niente da annullare su Eventbrite per questo evento.", show_alert=True)
                    query.edit_message_reply_markup.assert_not_called()
        self.cancel_only.assert_not_awaited()

    async def test_back_restores_the_card(self):
        event_id = self.linked()
        update, query = callback_update(f"cancel_abort_{event_id}", chat_id=999)
        with eventbrite_credentials():
            await handle_callback_query(update, self.context)
        keyboard = query.edit_message_reply_markup.call_args.kwargs["reply_markup"]
        self.assertIn(f"eb_cancel_ask_{event_id}", [b.callback_data for row in keyboard.inline_keyboard for b in row])


class TestEventbriteLogoRetryCallback(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_button_retries_the_logo_upload(self):
        event_id = create_event(status="approved")
        update, query = callback_update(f"eb_logo_{event_id}", chat_id=999)
        with patch("bot.callbacks.events.retry_logo_on_eventbrite", new_callable=AsyncMock) as retry:
            await handle_callback_query(update, make_context())
        query.answer.assert_awaited()
        retry.assert_awaited_once()
        self.assertEqual(retry.call_args.args[1:], (event_id, 999))


if __name__ == "__main__":
    unittest.main()


class TestStaleApprovalCard(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    """A second approval card (delivered by a timed-out upload) must not act on a published event."""

    async def test_discard_on_published_event_is_refused(self):
        event_id = create_event(status="approved")
        update, query = callback_update(f"discard_event_{event_id}", text=None, caption="Card", photo=True)
        await handle_callback_query(update, make_context())
        self.assertEqual(db.get_event(event_id)["status"], "approved")
        self.assertIn("già pubblicato", query.answer.call_args.args[0])
        self.assertIn("✅ APPROVATO", query.edit_message_caption.call_args.kwargs["caption"])

    async def test_publish_on_published_event_does_not_post_again(self):
        event_id = create_event(status="approved")
        update, query = callback_update(f"publish_event_{event_id}", text=None, caption="Card", photo=True)
        with patch("bot.callbacks.events._publish_to_channel", new_callable=AsyncMock) as post:
            await handle_callback_query(update, make_context())
        post.assert_not_awaited()
        self.assertTrue(query.answer.call_args.kwargs.get("show_alert"))

    async def test_discard_on_cancelled_event_is_refused(self):
        event_id = create_event(status="cancelled")
        update, query = callback_update(f"discard_event_{event_id}", text=None, caption="Card", photo=True)
        await handle_callback_query(update, make_context())
        self.assertIsNotNone(db.get_event(event_id))
        self.assertIn("annullato", query.answer.call_args.args[0])


class TestDeleteEventCallbacks(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.context = make_context()
        self.event_id = create_event(status="cancelled", telegram_message_id=11)

    def press(self, action, event_id=None):
        update, query = callback_update(f"{action}_{event_id or self.event_id}", text=None,
                                        caption="Card\n\n⚠️ ANNULLATO", photo=True)
        return update, query

    def markup_callbacks(self, query):
        markup = query.edit_message_reply_markup.call_args.kwargs["reply_markup"]
        return [b.callback_data for row in markup.inline_keyboard for b in row]

    async def test_delete_only_asks_for_confirmation(self):
        update, query = self.press("delete_event")
        await handle_callback_query(update, self.context)
        self.assertEqual(self.markup_callbacks(query),
                         [f"delete_confirm_{self.event_id}", f"delete_abort_{self.event_id}"])
        self.assertIsNotNone(db.get_event(self.event_id))

    async def test_abort_restores_the_cancelled_buttons(self):
        update, query = self.press("delete_abort")
        await handle_callback_query(update, self.context)
        self.assertEqual(query.answer.call_args.args[0], "Eliminazione interrotta.")
        self.assertIn(f"reactivate_event_{self.event_id}", self.markup_callbacks(query))
        self.assertIn(f"delete_event_{self.event_id}", self.markup_callbacks(query))

    async def test_confirm_deletes_and_marks_the_card(self):
        update, query = self.press("delete_confirm")
        with patched_config(PUBLIC_CHANNEL_ID="-1001"):
            await handle_callback_query(update, self.context)
        self.assertIsNone(db.get_event(self.event_id))
        self.context.bot.delete_message.assert_awaited_once_with(chat_id="-1001", message_id=11)
        caption = query.edit_message_caption.call_args.kwargs
        self.assertTrue(caption["caption"].endswith("🗑️ ELIMINATO"))
        self.assertNotIn("ANNULLATO", caption["caption"])
        self.assertEqual(caption["reply_markup"].inline_keyboard, ())
        self.context.bot.send_message.assert_not_awaited()  # nothing left over to report

    async def test_confirm_reports_messages_that_could_not_be_deleted(self):
        self.context.bot.delete_message.side_effect = Forbidden("no rights")
        update, query = self.press("delete_confirm")
        with patched_config(PUBLIC_CHANNEL_ID="-1001"):
            await handle_callback_query(update, self.context)
        self.assertIsNone(db.get_event(self.event_id))
        self.assertIn("post sul canale", self.context.bot.send_message.call_args.kwargs["text"])

    async def test_second_confirm_on_a_deleted_event(self):
        db.delete_event(self.event_id)
        update, query = self.press("delete_confirm")
        await handle_callback_query(update, self.context)
        self.assertEqual(query.answer.call_args.args[0], "Questo evento è già stato eliminato.")
        self.context.bot.delete_message.assert_not_awaited()

    async def test_only_cancelled_events_can_be_deleted(self):
        db.update_event_status(self.event_id, "approved")
        update, query = self.press("delete_confirm")
        await handle_callback_query(update, self.context)
        self.assertIsNotNone(db.get_event(self.event_id))
        self.assertIn("solo gli eventi annullati", query.answer.call_args.args[0])

    async def test_eventbrite_orders_still_open_block_the_deletion(self):
        db.set_eventbrite_info(self.event_id, eventbrite_event_id="eb1", eventbrite_status="closed")
        update, query = self.press("delete_confirm")
        with patch("bot.callbacks.events.delete_event_everywhere", new_callable=AsyncMock) as delete:
            await handle_callback_query(update, self.context)
        delete.assert_not_awaited()
        self.assertIsNotNone(db.get_event(self.event_id))
        self.assertIn("prenotazioni attive su Eventbrite", query.answer.call_args.args[0])

    async def test_eventbrite_refusal_keeps_the_event_and_the_buttons(self):
        update, query = self.press("delete_confirm")
        with patch("bot.callbacks.events.delete_event_everywhere", new_callable=AsyncMock,
                   return_value=DeletionResult(eventbrite_error="CANNOT_DELETE")):
            await handle_callback_query(update, self.context)
        self.assertIn("CANNOT_DELETE", self.context.bot.send_message.call_args.kwargs["text"])
        self.assertIn(f"delete_event_{self.event_id}", self.markup_callbacks(query))
        query.edit_message_caption.assert_not_awaited()

    async def test_reactivate_on_a_deleted_event_changes_nothing(self):
        db.delete_event(self.event_id)
        update, query = self.press("reactivate_event")
        with patch("bot.callbacks.events.update_event_messages", new_callable=AsyncMock) as refresh:
            await handle_callback_query(update, self.context)
        refresh.assert_not_awaited()
        query.edit_message_caption.assert_not_awaited()
        self.assertTrue(query.answer.call_args.kwargs.get("show_alert"))


class TestCommandConfirmationPrompts(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    """Confirm/back on the prompt sent by /event_cancel, /event_cancel_eventbrite, /event_delete (`_cmd` marker):
    the clicked message is the prompt, so the stored admin card is redrawn instead."""

    def setUp(self):
        super().setUp()
        self.context = make_context()
        self.update_messages = patch("bot.callbacks.events.update_event_messages", new_callable=AsyncMock).start()
        self.notice = patch("bot.callbacks.events.send_cancellation_notice", new_callable=AsyncMock).start()
        self.addCleanup(patch.stopall)

    def with_card(self, event_id):
        db.update_event_field(event_id, "admin_message_id", 500)
        return event_id

    def press(self, data):
        return callback_update(data, text="⚠️ Annullare l'evento?", message_id=900)

    def stored_card_edit(self):
        return self.context.bot.edit_message_caption.call_args.kwargs

    async def test_cancel_confirm_redraws_the_stored_card_and_closes_the_prompt(self):
        event_id = self.with_card(create_event(status="approved"))
        update, query = self.press(f"cancel_confirm_{event_id}_cmd")
        with patched_config(ADMIN_CHAT_ID="-100777"):
            await handle_callback_query(update, self.context)

        self.assertEqual(db.get_event(event_id)["status"], "cancelled")
        card = self.stored_card_edit()
        self.assertEqual((card["chat_id"], card["message_id"]), ("-100777", 500))
        self.assertTrue(card["caption"].endswith("⚠️ ANNULLATO"))
        self.assertIn(f"reactivate_event_{event_id}",
                      [b.callback_data for row in card["reply_markup"].inline_keyboard for b in row])
        self.assertEqual(query.edit_message_text.call_args.kwargs["text"], f"⚠️ Evento #{event_id} annullato.")
        self.assertNotIn("reply_markup", query.edit_message_text.call_args.kwargs)
        self.assertIsNone(self.update_messages.call_args.kwargs["current_query"])
        self.notice.assert_awaited_once()

    async def test_text_card_falls_back_to_a_text_edit(self):
        event_id = self.with_card(create_event(status="approved"))
        self.context.bot.edit_message_caption.side_effect = Exception("Bad Request: there is no caption in the message to edit")
        update, _query = self.press(f"cancel_confirm_{event_id}_cmd")
        with patched_config(ADMIN_CHAT_ID="-100777"):
            await handle_callback_query(update, self.context)
        self.assertTrue(self.context.bot.edit_message_text.call_args.kwargs["text"].endswith("⚠️ ANNULLATO"))

    async def test_without_a_stored_card_only_the_prompt_changes(self):
        event_id = create_event(status="approved")
        update, query = self.press(f"cancel_confirm_{event_id}_cmd")
        await handle_callback_query(update, self.context)
        self.assertEqual(db.get_event(event_id)["status"], "cancelled")
        self.context.bot.edit_message_caption.assert_not_awaited()
        query.edit_message_text.assert_awaited_once()

    async def test_cancel_abort_only_closes_the_prompt(self):
        event_id = self.with_card(create_event(status="approved"))
        update, query = self.press(f"cancel_abort_{event_id}_cmd")
        await handle_callback_query(update, self.context)
        self.assertEqual(query.edit_message_text.call_args.kwargs["text"], "Annullamento interrotto.")
        query.edit_message_reply_markup.assert_not_awaited()
        self.assertEqual(db.get_event(event_id)["status"], "approved")

    async def test_repeated_cancel_confirm_closes_the_prompt(self):
        event_id = create_event(status="cancelled")
        update, query = self.press(f"cancel_confirm_{event_id}_cmd")
        await handle_callback_query(update, self.context)
        self.notice.assert_not_awaited()
        self.assertEqual(query.edit_message_text.call_args.kwargs["text"], "Evento già annullato.")

    async def test_delete_confirm_from_a_command(self):
        event_id = self.with_card(create_event(status="cancelled", telegram_message_id=11))
        update, query = self.press(f"delete_confirm_{event_id}_cmd")
        with patched_config(ADMIN_CHAT_ID="-100777", PUBLIC_CHANNEL_ID="-1001"):
            await handle_callback_query(update, self.context)

        self.assertIsNone(db.get_event(event_id))
        self.context.bot.delete_message.assert_awaited_once_with(chat_id="-1001", message_id=11)
        card = self.stored_card_edit()
        self.assertTrue(card["caption"].endswith("🗑️ ELIMINATO"))
        self.assertEqual(card["reply_markup"].inline_keyboard, ())
        self.assertEqual(query.edit_message_text.call_args.kwargs["text"], f"🗑️ Evento #{event_id} eliminato.")

    async def test_delete_eventbrite_refusal_from_a_command_leaves_the_card(self):
        event_id = self.with_card(create_event(status="cancelled"))
        update, query = self.press(f"delete_confirm_{event_id}_cmd")
        with patch("bot.callbacks.events.delete_event_everywhere", new_callable=AsyncMock,
                   return_value=DeletionResult(eventbrite_error="CANNOT_DELETE")):
            await handle_callback_query(update, self.context)
        self.assertIn("CANNOT_DELETE", query.edit_message_text.call_args.kwargs["text"])
        self.context.bot.edit_message_caption.assert_not_awaited()
        self.assertIsNotNone(db.get_event(event_id))

    async def test_delete_abort_from_a_command(self):
        event_id = create_event(status="cancelled")
        update, query = self.press(f"delete_abort_{event_id}_cmd")
        await handle_callback_query(update, self.context)
        self.assertEqual(query.edit_message_text.call_args.kwargs["text"], "Eliminazione interrotta.")
        self.assertIsNotNone(db.get_event(event_id))

    async def test_delete_from_a_command_on_an_event_no_longer_cancelled(self):
        event_id = create_event(status="approved")
        update, query = self.press(f"delete_confirm_{event_id}_cmd")
        await handle_callback_query(update, self.context)
        self.assertIn("solo gli eventi annullati", query.edit_message_text.call_args.kwargs["text"])
        self.assertIsNotNone(db.get_event(event_id))

    async def test_eventbrite_cancel_from_a_command(self):
        event_id = create_event(status="approved")
        db.set_eventbrite_info(event_id, eventbrite_event_id="eb1", eventbrite_status="live")
        update, query = self.press(f"eb_cancel_do_{event_id}_cmd")
        with patch("bot.callbacks.events.cancel_only_on_eventbrite", new_callable=AsyncMock) as cancel:
            await handle_callback_query(update, self.context)
        cancel.assert_awaited_once()
        self.assertEqual(cancel.call_args.args[1]["id"], event_id)
        self.assertIn("Eventbrite", query.edit_message_text.call_args.kwargs["text"])

    async def test_eventbrite_cancel_from_a_command_with_nothing_to_cancel(self):
        event_id = create_event(status="approved")
        update, query = self.press(f"eb_cancel_do_{event_id}_cmd")
        with patch("bot.callbacks.events.cancel_only_on_eventbrite", new_callable=AsyncMock) as cancel:
            await handle_callback_query(update, self.context)
        cancel.assert_not_awaited()
        self.assertEqual(query.edit_message_text.call_args.kwargs["text"],
                         "Niente da annullare su Eventbrite per questo evento.")
