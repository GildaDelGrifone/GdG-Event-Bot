import unittest
from unittest.mock import AsyncMock, patch

import core.db as db
from bot.handlers.eventbrite import event_publish_eventbrite_command
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import ADMIN_CHAT_ID, admin_card, admin_update, make_context, make_message, make_update


class TestEventPublishEventbriteCommand(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.event_id = create_event(status="approved", title="Avventura")
        self.context = make_context()
        patcher = patch("bot.handlers.eventbrite.start_eventbrite_publish", new_callable=AsyncMock)
        self.publish = patcher.start()
        self.addCleanup(patcher.stop)

    async def run_command(self, update):
        with as_admin_chat():
            await event_publish_eventbrite_command(update, self.context)

    def reply_texts(self, update):
        return [call.args[0] for call in update.message.reply_text.call_args_list]

    async def test_event_id_from_the_replied_card(self):
        update = admin_update("/event_publish_eventbrite", reply_to=admin_card(self.event_id))
        await self.run_command(update)
        # Same arguments the [🎟️ Pubblica su Eventbrite] button passes: (context, event_id, chat of the message)
        self.publish.assert_awaited_once_with(self.context, self.event_id, int(ADMIN_CHAT_ID))
        update.message.reply_text.assert_not_called()

    async def test_event_id_from_the_argument(self):
        update = admin_update(f"/event_publish_eventbrite {self.event_id}")
        await self.run_command(update)
        self.publish.assert_awaited_once_with(self.context, self.event_id, int(ADMIN_CHAT_ID))

    async def test_missing_id_shows_the_usage(self):
        for text in ("/event_publish_eventbrite", "/event_publish_eventbrite abc"):
            update = admin_update(text)
            await self.run_command(update)
            self.assertEqual(self.reply_texts(update), [
                "❌ Rispondi al messaggio di un evento (quello con i pulsanti) oppure usa: /event_publish_eventbrite <id>"])
        self.publish.assert_not_called()

    async def test_reply_to_a_non_event_message_falls_back_to_the_usage(self):
        stray = make_message(text="ciao")
        stray.reply_markup = None
        update = admin_update("/event_publish_eventbrite", reply_to=stray)
        await self.run_command(update)
        self.assertIn("Rispondi al messaggio di un evento", self.reply_texts(update)[0])
        self.publish.assert_not_called()

    async def test_unknown_event(self):
        update = admin_update("/event_publish_eventbrite 999")
        await self.run_command(update)
        self.assertEqual(self.reply_texts(update), ["❌ Evento #999 non trovato"])
        self.publish.assert_not_called()

    async def test_pending_event(self):
        pending = create_event(status="pending")
        update = admin_update(f"/event_publish_eventbrite {pending}")
        await self.run_command(update)
        self.assertEqual(self.reply_texts(update),
                         ["❌ Pubblica prima l'evento su Telegram (oppure usa 🚀 Publish + Eventbrite sulla scheda)"])
        self.publish.assert_not_called()

    async def test_cancelled_event(self):
        db.update_event_status(self.event_id, "cancelled")
        update = admin_update(f"/event_publish_eventbrite {self.event_id}")
        await self.run_command(update)
        self.assertEqual(self.reply_texts(update), ["❌ Evento annullato: riattivalo prima"])
        self.publish.assert_not_called()

    async def test_non_admin_is_ignored(self):
        update = make_update(chat_id=11111, text=f"/event_publish_eventbrite {self.event_id}")
        await self.run_command(update)
        self.publish.assert_not_called()
        update.message.reply_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
