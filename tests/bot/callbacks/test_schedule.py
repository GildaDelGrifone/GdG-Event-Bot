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


if __name__ == "__main__":
    unittest.main()
