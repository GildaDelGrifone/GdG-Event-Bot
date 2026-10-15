import unittest
from datetime import datetime
from unittest.mock import patch

from bot.handlers.recap import manual_recap_command
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import admin_update, make_context


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


if __name__ == "__main__":
    unittest.main()
