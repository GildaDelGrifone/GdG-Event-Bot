import unittest
from datetime import datetime

import core.db as db
from core.scheduler.reposts import format_reposts_digest, send_daily_scheduled_reposts
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin
from tests.support.telegram import make_bot

DAYS_IT = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


class TestRepostDigest(unittest.TestCase):
    def test_titles_are_html_escaped(self):
        text = format_reposts_digest([{"id": 3, "title": "D&D <Oneshot>"}], "Lunedì", "05-10-2026")
        self.assertIn("D&amp;D &lt;Oneshot&gt;", text)
        self.assertIn("/event_schedule_invoke 3", text)


class TestDailyScheduledReposts(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_send_daily_scheduled_reposts_job(self):
        sched_id = db.insert_scheduled_event(
            title="Evento Ricorrente Oggi",
            text="Titolo: Evento Ricorrente Oggi\nPosti: 4/4",
            schedule_days=[DAYS_IT[datetime.now().weekday()]],
        )
        bot = make_bot()

        with as_admin_chat():
            await send_daily_scheduled_reposts(bot)

        bot.send_message.assert_called_once()
        msg_text = bot.send_message.call_args[1]["text"]
        self.assertIn(f"/event_schedule_invoke {sched_id}", msg_text)
        self.assertIn("/event_schedule_update", msg_text)
        self.assertIn("Evento Ricorrente Oggi", msg_text)


if __name__ == "__main__":
    unittest.main()
