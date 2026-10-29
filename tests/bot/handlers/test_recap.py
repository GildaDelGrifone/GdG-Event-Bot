import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import core.db as db
from bot.handlers.recap import handle_discussion_forward, manual_recap_command, recap_article_command
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin, create_event
from bot.state import runtime_state
from tests.support.telegram import admin_update, make_context, make_message, make_update


class TestRecapArticleCommand(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def _run(self, args, events=(), update=None):
        update = update or admin_update(message_id=5)
        context = make_context(args=args)
        with as_admin_chat(), \
             patch("bot.handlers.recap.get_pending_events_for_recap", return_value=list(events)) as load, \
             patch("bot.handlers.recap.run_article_pipeline") as pipeline:
            await recap_article_command(update, context)
        return update, context, load, pipeline

    async def test_regenerates_the_article_for_the_given_date(self):
        events = [{"id": 1}]
        update, context, load, pipeline = await self._run(["23-10-2026"], events)

        load.assert_called_once_with("23-10-2026")
        pipeline.assert_called_once_with(context.bot, "999", "23-10-2026", events)
        self.assertIn("23-10-2026", update.message.reply_text.call_args[0][0])

    async def test_defaults_to_today(self):
        _update, _context, load, pipeline = await self._run([], [{"id": 1}])

        load.assert_called_once_with(datetime.now().strftime("%d-%m-%Y"))
        pipeline.assert_called_once()

    async def test_invalid_date_is_rejected(self):
        update, _context, load, pipeline = await self._run(["nope"])

        self.assertIn("Formato data non valido", update.message.reply_text.call_args[0][0])
        load.assert_not_called()
        pipeline.assert_not_called()

    async def test_no_events_replies_without_running_the_pipeline(self):
        update, _context, _load, pipeline = await self._run(["15-09-2026"])

        self.assertEqual(update.message.reply_text.call_args[0][0], "Nessun evento in programma per la data 15-09-2026.")
        pipeline.assert_not_called()

    async def test_non_admin_is_ignored(self):
        update = make_update(text="/recap_article", chat_id=1, user=MagicMock(id=1, username="x"))
        _update, _context, load, pipeline = await self._run([], [{"id": 1}], update=update)

        load.assert_not_called()
        pipeline.assert_not_called()


class TestManualRecapCommand(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def _recap(self, args, message_id=1, send_side_effect=None):
        update = admin_update(message_id=message_id)
        context = make_context(args=args)
        context.bot.send_message.side_effect = send_side_effect
        with as_admin_chat(DATA_DIR=self.temp_dir.name), patch("core.scheduler.recap.create_collage", return_value=None):
            await manual_recap_command(update, context)
        return update, context.bot.send_message

    async def test_manual_recap_command_no_events_today(self):
        update, send_message = await self._recap([], message_id=777)

        send_message.assert_called_once()
        call_kwargs = send_message.call_args.kwargs
        self.assertEqual(call_kwargs["chat_id"], "999")
        self.assertEqual(call_kwargs["text"], "Nessun evento in programma per oggi.")
        self.assertEqual(call_kwargs["reply_to_message_id"], 777)
        update.message.reply_text.assert_not_called()

    async def test_manual_recap_command_no_events_reply_exception_fallback(self):
        _update, send_message = await self._recap([], message_id=777,
                                                  send_side_effect=[Exception("Message not found"), None])

        # First attempt with reply_to_message_id failed, second fallback attempt without it succeeded
        self.assertEqual(send_message.call_count, 2)
        fallback_kwargs = send_message.call_args.kwargs
        self.assertEqual(fallback_kwargs["chat_id"], "999")
        self.assertEqual(fallback_kwargs["text"], "Nessun evento in programma per oggi.")
        self.assertNotIn("reply_to_message_id", fallback_kwargs)

    async def test_manual_recap_command_no_events_specific_date(self):
        update, send_message = await self._recap(["15-09-2026"], message_id=778)

        send_message.assert_called_once()
        call_kwargs = send_message.call_args.kwargs
        self.assertEqual(call_kwargs["chat_id"], "999")
        self.assertEqual(call_kwargs["text"], "Nessun evento in programma per la data 15-09-2026.")
        self.assertEqual(call_kwargs["reply_to_message_id"], 778)
        update.message.reply_text.assert_not_called()

    async def test_manual_recap_command_invalid_date_format(self):
        update, _send_message = await self._recap(["not-a-valid-date"])

        update.message.reply_text.assert_called_once()
        self.assertIn("Formato data non valido", update.message.reply_text.call_args[0][0])

    async def test_manual_recap_command_with_events_today(self):
        create_event(
            status="approved", original_text="test text", title="Partita di Oggi", date="Oggi 21:00",
            normalized_date=datetime.now().strftime("%d-%m-%Y"), system="Pathfinder", host="Master Luke",
            seats="3/4", booked_seats=1, max_seats=4, description="Avventura serale",
        )

        update, send_message = await self._recap([], message_id=888)

        send_message.assert_called_once()
        recap_call_kwargs = send_message.call_args.kwargs
        self.assertEqual(recap_call_kwargs["chat_id"], "999")
        self.assertIn("Partita di Oggi", recap_call_kwargs["text"])
        update.message.reply_text.assert_called_once_with("Recap generato per la data: Oggi")


class TestDiscussionForward(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.event_id = create_event(status="approved", telegram_message_id=777)
        self.context = make_context(bot_username="test_bot")
        # Other tests publish a recap as message 777; make sure it is not remembered here
        recap_patch = patch.object(runtime_state, "last_recap_message_id", None)
        recap_patch.start()
        self.addCleanup(recap_patch.stop)

    def forward(self):
        message = make_message(chat_id=-100222, message_id=888)
        message.is_automatic_forward = True
        message.forward_origin = MagicMock(type="channel", message_id=777)
        return make_update(message=message)

    async def test_first_forward_posts_the_booking_reply_without_a_link(self):
        await handle_discussion_forward(self.forward(), self.context)

        call = self.context.bot.send_message.call_args.kwargs
        self.assertEqual(call["text"], "👇 Gestisci qui la tua prenotazione!")
        self.assertEqual((call["parse_mode"], call["disable_web_page_preview"]), ("HTML", True))
        self.assertEqual(call["reply_to_message_id"], 888)
        self.assertIsNotNone(call["reply_markup"])

    async def test_forward_of_an_eventbrite_event_includes_the_link(self):
        db.set_eventbrite_info(self.event_id, eventbrite_url="https://eventbrite.example/e/1", eventbrite_status="live")

        await handle_discussion_forward(self.forward(), self.context)

        text = self.context.bot.send_message.call_args.kwargs["text"]
        self.assertIn("🎟️ Prenota anche su Eventbrite: <a href=\"https://eventbrite.example/e/1\">link</a>", text)

    async def test_link_published_while_the_reply_was_being_sent_is_added_afterwards(self):
        async def publish_finishes_meanwhile(**kwargs):
            db.set_eventbrite_info(self.event_id, eventbrite_url="https://eventbrite.example/e/1", eventbrite_status="live")
            return MagicMock(chat_id=-100222, message_id=4242)
        self.context.bot.send_message.side_effect = publish_finishes_meanwhile

        await handle_discussion_forward(self.forward(), self.context)

        call = self.context.bot.edit_message_text.call_args.kwargs
        self.assertEqual((call["chat_id"], call["message_id"]), (-100222, 4242))
        self.assertIn("Prenota anche su Eventbrite", call["text"])

    async def test_no_extra_edit_when_nothing_changed(self):
        await handle_discussion_forward(self.forward(), self.context)
        self.context.bot.edit_message_text.assert_not_called()

    async def test_existing_reply_is_edited_as_text_with_the_link(self):
        db.update_discussion_message_info(self.event_id, 4242, -100222)
        db.set_eventbrite_info(self.event_id, eventbrite_url="https://eventbrite.example/e/1", eventbrite_status="live")

        await handle_discussion_forward(self.forward(), self.context)

        self.context.bot.send_message.assert_not_called()
        call = self.context.bot.edit_message_text.call_args.kwargs
        self.assertEqual((call["chat_id"], call["message_id"]), (-100222, 4242))
        self.assertIn("Eventbrite", call["text"])
        self.assertEqual((call["parse_mode"], call["disable_web_page_preview"]), ("HTML", True))


if __name__ == "__main__":
    unittest.main()
