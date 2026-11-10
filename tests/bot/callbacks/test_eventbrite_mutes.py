import unittest
from unittest.mock import patch

import core.db as db
import bot.service.eventbrite_poll as poller
from bot.callbacks.router import handle_callback_query
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin, create_subscribed_event
from tests.support.telegram import callback_update, make_context, make_user

ALERT = "🔇 Giovanni F. ha annullato 3 prenotazioni Eventbrite in 60 minuti per: Avventura"


class MuteCase(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.event_id = create_subscribed_event()
        self.mute_id = db.mute_eventbrite_name(self.event_id, "Giovanni F.")
        poller._release_times.clear()
        poller._release_times[(self.event_id, "Giovanni F.")] = [1.0, 2.0, 3.0]
        poller._release_times[(self.event_id, "Anna B.")] = [1.0]
        self.addCleanup(poller._release_times.clear)

    async def press(self, data, **kwargs):
        update, query = callback_update(data, user=make_user(998877, "admin_boss"), **kwargs)
        with as_admin_chat():
            await handle_callback_query(update, make_context())
        return query


class TestAlertButton(MuteCase):
    async def test_unmutes_resets_the_history_and_marks_the_alert(self):
        with self.assertLogs("bot.callbacks.eventbrite_mutes", level="INFO") as logs:
            query = await self.press(f"ebmute_clear_{self.mute_id}", text=ALERT)

        self.assertEqual(db.get_eventbrite_mutes(self.event_id), [])
        self.assertNotIn((self.event_id, "Giovanni F."), poller._release_times)
        self.assertIn((self.event_id, "Anna B."), poller._release_times)  # other names keep their history
        query.answer.assert_awaited_with("Annunci riattivati")
        kwargs = query.edit_message_text.call_args.kwargs
        self.assertTrue(kwargs["text"].startswith(ALERT))
        self.assertTrue(kwargs["text"].endswith("🔔 Annunci riattivati da @admin_boss."))
        self.assertIsNone(kwargs["reply_markup"])
        self.assertTrue(any('998877' in line and '"Giovanni F."' in line for line in logs.output))

    async def test_a_cleared_mute_answers_with_a_popup(self):
        db.unmute_eventbrite(self.mute_id)
        query = await self.press(f"ebmute_clear_{self.mute_id}", text=ALERT)
        query.answer.assert_awaited_with("Già riattivati.", show_alert=True)
        query.edit_message_text.assert_not_awaited()

    async def test_outsiders_cannot_unmute(self):
        update, query = callback_update(f"ebmute_clear_{self.mute_id}", chat_id=-100123)
        with as_admin_chat():
            await handle_callback_query(update, make_context())
        self.assertEqual(len(db.get_eventbrite_mutes(self.event_id)), 1)
        query.edit_message_text.assert_not_awaited()


class TestPanelButton(MuteCase):
    async def test_unmutes_and_redraws_the_panel(self):
        query = await self.press(f"ebmute_panel_{self.mute_id}", text="👥 Gestione Iscritti")

        self.assertEqual(db.get_eventbrite_mutes(self.event_id), [])
        kwargs = query.edit_message_text.call_args.kwargs
        self.assertIn("Gestione Iscritti", kwargs["text"])
        self.assertNotIn("🔇", kwargs["text"])
        callbacks = [b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row]
        self.assertFalse(any(c and c.startswith("ebmute_panel_") for c in callbacks))


if __name__ == "__main__":
    unittest.main()
