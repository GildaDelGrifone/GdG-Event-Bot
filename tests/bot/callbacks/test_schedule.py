import unittest

import core.db as db
from bot.callbacks.router import handle_callback_query
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin
from tests.support.telegram import callback_update, make_context


class TestScheduleToggleCallback(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_schedule_toggle_callback(self):
        sched_id = db.insert_scheduled_event(title="Serata GdT", text="Testo evento", schedule_days=["Lunedì"])
        update, query = callback_update(f"sched_toggle_{sched_id}_mer")
        context = make_context()

        with as_admin_chat():
            await handle_callback_query(update, context)

        ev = db.get_scheduled_event(sched_id)
        self.assertIn("Mercoledì", ev["schedule_days"])
        self.assertIn("Lunedì", ev["schedule_days"])

        # Toggle again to deactivate Mercoledì
        query.data = f"sched_toggle_{sched_id}_mer"
        with as_admin_chat():
            await handle_callback_query(update, context)

        ev = db.get_scheduled_event(sched_id)
        self.assertNotIn("Mercoledì", ev["schedule_days"])
        self.assertIn("Lunedì", ev["schedule_days"])


class TestScheduleAdvanceCallback(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def _press(self, sched_id, action):
        update, query = callback_update(f"sched_adv_{sched_id}_{action}")
        with as_admin_chat():
            await handle_callback_query(update, make_context())
        return query

    async def test_inc_dec_and_clamp(self):
        sched_id = db.insert_scheduled_event(title="Serata", text="Testo")
        await self._press(sched_id, "dec")
        self.assertEqual(db.get_scheduled_event(sched_id)["advance_days"], 0)
        await self._press(sched_id, "inc")
        await self._press(sched_id, "inc")
        self.assertEqual(db.get_scheduled_event(sched_id)["advance_days"], 2)
        await self._press(sched_id, "dec")
        self.assertEqual(db.get_scheduled_event(sched_id)["advance_days"], 1)
        await self._press(sched_id, "noop")
        self.assertEqual(db.get_scheduled_event(sched_id)["advance_days"], 1)

        db.update_scheduled_event_advance_days(sched_id, 30)
        await self._press(sched_id, "inc")
        self.assertEqual(db.get_scheduled_event(sched_id)["advance_days"], 30)

    async def test_card_is_re_rendered_with_new_value(self):
        sched_id = db.insert_scheduled_event(title="Serata", text="Testo")
        query = await self._press(sched_id, "inc")
        edited = query.edit_message_text.call_args[1] if query.edit_message_text.called else query.edit_message_caption.call_args[1]
        self.assertIn("1 giorno prima", edited.get("text") or edited["caption"])
        self.assertEqual(edited["reply_markup"].inline_keyboard[2][1].text, "⏳ Anticipo: 1 gg")


if __name__ == "__main__":
    unittest.main()
