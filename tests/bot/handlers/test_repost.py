import unittest
from datetime import date, datetime
from unittest.mock import patch

import core.db as db
from bot.handlers.repost import _invoke_overrides, event_repost_command, event_schedule_invoke_command
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin
from tests.support.telegram import admin_update, make_context, make_message


class TestEventRepost(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_event_repost_command(self):
        reply_msg = make_message(
            text="Titolo: Cthulhu Hack\nData: 01-01-2026 21:00\nPosti: 2/4\nDescrizione: Investigazione ad Arkham",
            message_id=555,
        )
        reply_msg.reply_markup = None
        reply_msg.link = "https://t.me/c/999/555"
        update = admin_update("/event_repost oggi 5", reply_to=reply_msg)

        parsed = {
            "is_event": True,
            "title": "Cthulhu Hack",
            "date": "01-01-2026 21:00",
            "normalized_date": "01-01-2026",
            "system": "Call of Cthulhu",
            "host": "Keeper",
            "seats": "2/4",
            "max_seats": 4,
            "booked_seats": 0,
            "description": "Investigazione ad Arkham",
        }
        with as_admin_chat(), patch("bot.handlers.extraction.parse_event_message", return_value=parsed):
            await event_repost_command(update, make_context())

        update.message.reply_text.assert_called()
        self.assertIn("ripubblicato ed elaborato", update.message.reply_text.call_args[0][0])

        upcoming = db.get_upcoming_events(include_today=True)
        self.assertTrue(len(upcoming) > 0)
        newest = upcoming[-1]
        self.assertEqual(newest["normalized_date"], datetime.now().strftime("%d-%m-%Y"))
        self.assertEqual(newest["max_seats"], 5)
        self.assertEqual(newest["seats"], "5/5")

    async def test_event_schedule_invoke_command(self):
        sched_id = db.insert_scheduled_event(
            title="Cyberpunk Red",
            text="Titolo: Cyberpunk Red\nData: 01-01-2026\nPosti: 3/3\nDescrizione: Missione a Night City",
            schedule_days=["Lunedì"],
            specific_date="01-01-2026 21:00",
        )
        update = admin_update(f"/event_schedule_invoke {sched_id}")

        parsed = {
            "is_event": True,
            "title": "Cyberpunk Red",
            "date": "01-01-2026 21:00",
            "normalized_date": "01-01-2026",
            "system": "Cyberpunk Red",
            "host": "Fixer",
            "seats": "3/3",
            "max_seats": 3,
            "booked_seats": 0,
            "description": "Missione a Night City",
        }
        with as_admin_chat(), patch("bot.handlers.extraction.parse_event_message", return_value=parsed):
            await event_schedule_invoke_command(update, make_context())

        update.message.reply_text.assert_called()
        self.assertIn("invocato e pronto per la revisione", update.message.reply_text.call_args[0][0])

        upcoming = db.get_upcoming_events(include_today=True)
        created_event = [e for e in upcoming if e["title"] == "Cyberpunk Red"][0]
        self.assertEqual(created_event["normalized_date"], datetime.now().strftime("%d-%m-%Y"))


class TestInvokeOverrides(unittest.TestCase):
    SATURDAY_TEMPLATE = {"schedule_days": ["Sabato"], "advance_days": 2, "specific_date": None}

    def test_without_advance_the_default_is_today_with_template_time(self):
        self.assertEqual(_invoke_overrides({"schedule_days": ["Sabato"]}, []), ("oggi", None))
        self.assertEqual(_invoke_overrides({"specific_date": "01-01-2026 21:00"}, []), ("oggi 21:00", None))

    def test_with_advance_the_default_is_the_next_occurrence(self):
        thursday, saturday, sunday = date(2026, 10, 22), date(2026, 10, 24), date(2026, 10, 25)
        self.assertEqual(_invoke_overrides(self.SATURDAY_TEMPLATE, [], today=thursday), ("24-10-2026", None))
        self.assertEqual(_invoke_overrides(self.SATURDAY_TEMPLATE, [], today=saturday), ("oggi", None))  # same day
        self.assertEqual(_invoke_overrides(self.SATURDAY_TEMPLATE, [], today=sunday), ("31-10-2026", None))

    def test_explicit_date_wins_and_gets_the_template_time(self):
        sched_ev = {**self.SATURDAY_TEMPLATE, "specific_date": "24-10-2026 21:00"}
        self.assertEqual(_invoke_overrides(sched_ev, ["24-10-2026"]), ("24-10-2026 21:00", None))
        self.assertEqual(_invoke_overrides(sched_ev, ["24-10-2026", "18:00", "4"]), ("24-10-2026 18:00", "4"))
        self.assertEqual(_invoke_overrides(sched_ev, ["4/4"], today=date(2026, 10, 22)), ("24-10-2026 21:00", "4/4"))


if __name__ == "__main__":
    unittest.main()
