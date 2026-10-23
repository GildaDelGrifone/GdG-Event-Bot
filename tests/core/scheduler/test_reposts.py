import unittest
from datetime import date, datetime, timedelta

import core.db as db
from core.scheduler.reposts import format_reposts_digest, send_daily_scheduled_reposts
from utils.templates.reposts import format_reposts_digest_entry
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin
from tests.support.telegram import make_bot

DAYS_IT = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


class TestRepostDigest(unittest.TestCase):
    def test_titles_are_html_escaped(self):
        text = format_reposts_digest([({"id": 3, "title": "D&D <Oneshot>"}, date(2026, 10, 5))], "Lunedì", "05-10-2026")
        self.assertIn("D&amp;D &lt;Oneshot&gt;", text)
        self.assertIn("/event_schedule_invoke 3 05-10-2026", text)

    def test_entry_shows_event_day_and_keeps_template_time(self):
        entry = format_reposts_digest_entry(
            {"id": 4, "title": "Cena", "advance_days": 2, "specific_date": "Sabato 10-10-2026 21:00"}, date(2026, 10, 10))
        self.assertIn("Sabato 10-10-2026 (tra 2 giorni)", entry)
        self.assertIn("/event_schedule_invoke 4 10-10-2026 21:00", entry)
        self.assertIn("(domani)", format_reposts_digest_entry({"id": 4, "advance_days": 1}, date(2026, 10, 10)))


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

    async def test_reminder_is_sent_advance_days_before_the_event(self):
        event_day = datetime.now() + timedelta(days=3)
        sched_id = db.insert_scheduled_event(
            title="Serata Anticipata", text="Titolo: Serata\nPosti: 4/4",
            schedule_days=[DAYS_IT[event_day.weekday()]], advance_days=3,
        )
        bot = make_bot()

        with as_admin_chat():
            await send_daily_scheduled_reposts(bot)

        msg_text = bot.send_message.call_args[1]["text"]
        self.assertIn(f"/event_schedule_invoke {sched_id} {event_day.strftime('%d-%m-%Y')}", msg_text)

    async def test_no_reminder_when_event_is_not_n_days_ahead(self):
        db.insert_scheduled_event(
            title="X", text="t", schedule_days=[DAYS_IT[(datetime.now() + timedelta(days=2)).weekday()]], advance_days=3,
        )
        bot = make_bot()

        with as_admin_chat():
            await send_daily_scheduled_reposts(bot)

        bot.send_message.assert_not_called()
