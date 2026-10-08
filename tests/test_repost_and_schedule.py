import os
import tempfile
import unittest
from datetime import datetime, date
from unittest.mock import AsyncMock, MagicMock, patch

import core.db as db
from core import config
from bot.handlers.repost import event_repost_command, event_repost_invoke_command
from bot.handlers.repost_schedule import event_repost_schedule_command, event_repost_update_command, event_repost_list_command
from bot.handlers.edit import event_edit_command
from utils.templates import format_schedule_repost_message
from bot.keyboards import get_schedule_repost_keyboard
from bot.callbacks.router import handle_callback_query
from core.scheduler.reposts import send_daily_scheduled_reposts
from utils.date_utils import parse_user_date, format_standard_event_date


class TestRepostAndSchedule(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = os.path.join(self.temp_dir.name, "test_bot.db")
        db.init_db()

    def tearDown(self):
        config.DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()

    # 1. Date utils: "oggi", "LUN", "MER", "VEN"
    def test_date_utils_keywords_oggi_and_days(self):
        ref_dt = datetime(2026, 10, 7, 10, 0)

        # "oggi"
        dt, has_time = parse_user_date("oggi", reference_date=ref_dt)
        self.assertEqual(dt.date(), date(2026, 10, 7))
        self.assertFalse(has_time)

        # "oggi 21:00"
        dt, has_time = parse_user_date("oggi 21:00", reference_date=ref_dt)
        self.assertEqual(dt, datetime(2026, 10, 7, 21, 0))
        self.assertTrue(has_time)

        # "MER" when today is Wednesday -> next Wednesday (2026-10-14)
        dt, has_time = parse_user_date("MER", reference_date=ref_dt)
        self.assertEqual(dt.date(), date(2026, 10, 14))
        self.assertFalse(has_time)

        # "VEN" when today is Wednesday -> this Friday (2026-10-09)
        dt, has_time = parse_user_date("VEN 20:45", reference_date=ref_dt)
        self.assertEqual(dt, datetime(2026, 10, 9, 20, 45))
        self.assertTrue(has_time)

        # "LUN" when today is Wednesday -> next Monday (2026-10-12)
        dt, has_time = parse_user_date("LUN", reference_date=ref_dt)
        self.assertEqual(dt.date(), date(2026, 10, 12))
        self.assertFalse(has_time)

        # Edge case: today is Monday (2026-10-05) and user inputs "LUN" -> next Monday (2026-10-12)
        mon_dt = datetime(2026, 10, 5, 14, 0)
        dt, has_time = parse_user_date("LUN", reference_date=mon_dt)
        self.assertEqual(dt.date(), date(2026, 10, 12))
        self.assertFalse(has_time)

    # 2. /event_edit_date with "oggi" and "LUN"
    async def test_event_edit_date_supports_oggi_and_lun(self):
        ev_id = db.insert_event({
            "title": "Partita di Prova",
            "date": "Venerdì 04-09-2026",
            "normalized_date": "04-09-2026",
            "system": "D&D 5e",
            "host": "DM",
            "seats": "4/4",
            "max_seats": 4,
            "description": "Una bella avventura"
        }, None, "Testo originale")

        update = MagicMock()
        update.effective_chat.id = 999
        update.message.reply_to_message = MagicMock()
        update.message.reply_to_message.reply_markup.inline_keyboard = [[MagicMock(callback_data=f"publish_event_{ev_id}")]]
        update.message.reply_to_message.photo = None
        update.message.reply_to_message.text = "Event text"
        update.message.reply_to_message.edit_text = AsyncMock()
        update.message.reply_text = AsyncMock()

        update.message.text = "/event_edit_date oggi"
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await event_edit_command(update, context)

        ev = db.get_event(ev_id)
        today_norm = datetime.now().strftime("%d-%m-%Y")
        self.assertEqual(ev["normalized_date"], today_norm)

    # 3. Scheduled events DB CRUD
    def test_scheduled_events_db_crud(self):
        sched_id = db.insert_scheduled_event(
            title="D&D One-Shot",
            text="Titolo: D&D One-Shot\nData: 09-10-2026 21:00\nPosti: 4/4",
            image_path="/tmp/test.jpg",
            schedule_days=["Lunedì", "Venerdì"],
            specific_date="09-10-2026 21:00"
        )
        self.assertIsNotNone(sched_id)

        ev = db.get_scheduled_event(sched_id)
        self.assertEqual(ev["title"], "D&D One-Shot")
        self.assertEqual(ev["schedule_days"], ["Lunedì", "Venerdì"])
        self.assertEqual(ev["specific_date"], "09-10-2026 21:00")

        # Update days
        ok = db.update_scheduled_event_days(sched_id, ["Mercoledì", "Sabato"])
        self.assertTrue(ok)
        ev = db.get_scheduled_event(sched_id)
        self.assertEqual(ev["schedule_days"], ["Mercoledì", "Sabato"])

        # Update specific date
        ok = db.update_scheduled_event_specific_date(sched_id, "15-10-2026 20:30")
        self.assertTrue(ok)
        ev = db.get_scheduled_event(sched_id)
        self.assertEqual(ev["specific_date"], "15-10-2026 20:30")

        # Update content (/event_repost_update)
        ok = db.update_scheduled_event_content(sched_id, "Nuovo testo", title="Nuovo Titolo")
        self.assertTrue(ok)
        ev = db.get_scheduled_event(sched_id)
        self.assertEqual(ev["title"], "Nuovo Titolo")
        self.assertEqual(ev["text"], "Nuovo testo")

        # Get for date matching
        matches = db.get_scheduled_events_for_date("15-10-2026", "Mercoledì")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["id"], sched_id)

        # Delete
        db.delete_scheduled_event(sched_id)
        self.assertIsNone(db.get_scheduled_event(sched_id))

    # 4. /event_repost DATE SEATS
    async def test_event_repost_command(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.effective_user.id = 123
        update.effective_user.username = "testadmin"

        reply_msg = MagicMock()
        reply_msg.text = "Titolo: Cthulhu Hack\nData: 01-01-2026 21:00\nPosti: 2/4\nDescrizione: Investigazione ad Arkham"
        reply_msg.caption = None
        reply_msg.photo = None
        reply_msg.document = None
        reply_msg.reply_markup = None
        reply_msg.message_id = 555
        reply_msg.link = "https://t.me/c/999/555"

        update.message.reply_to_message = reply_msg
        update.message.text = "/event_repost oggi 5"
        update.message.caption = None
        update.message.photo = None
        update.message.document = None
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.extraction.parse_event_message", return_value={
                 "is_event": True,
                 "title": "Cthulhu Hack",
                 "date": "01-01-2026 21:00",
                 "normalized_date": "01-01-2026",
                 "system": "Call of Cthulhu",
                 "host": "Keeper",
                 "seats": "2/4",
                 "max_seats": 4,
                 "booked_seats": 0,
                 "description": "Investigazione ad Arkham"
             }):
            await event_repost_command(update, context)

        update.message.reply_text.assert_called()
        self.assertIn("ripubblicato ed elaborato", update.message.reply_text.call_args[0][0])

        upcoming = db.get_upcoming_events(include_today=True)
        self.assertTrue(len(upcoming) > 0)
        newest = upcoming[-1]
        today_norm = datetime.now().strftime("%d-%m-%Y")
        self.assertEqual(newest["normalized_date"], today_norm)
        self.assertEqual(newest["max_seats"], 5)
        self.assertEqual(newest["seats"], "5/5")

    # 5. /event_repost_schedule
    async def test_event_repost_schedule_creates_scheduled_event_with_keyboard(self):
        update = MagicMock()
        update.effective_chat.id = 999

        reply_msg = MagicMock()
        reply_msg.text = "Titolo: Gioco da Tavolo\nData: 10-10-2026 21:00\nPosti: 4/4\nDescrizione: Serata Boardgame"
        reply_msg.caption = None
        reply_msg.photo = None
        reply_msg.document = None
        reply_msg.reply_markup = None
        reply_msg.message_id = 777

        update.message.reply_to_message = reply_msg
        update.message.text = "/event_repost_schedule"
        update.message.caption = None
        update.message.photo = None
        update.message.document = None
        update.message.reply_text = AsyncMock()

        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await event_repost_schedule_command(update, context)

        update.message.reply_text.assert_called_once()
        sent_text = update.message.reply_text.call_args[0][0]
        sent_kb = update.message.reply_text.call_args[1]["reply_markup"]

        self.assertIn("Programmazione Repost Evento", sent_text)
        self.assertEqual(len(sent_kb.inline_keyboard), 3)
        self.assertEqual(len(sent_kb.inline_keyboard[0]), 3)  # Lun, Mer, Ven
        self.assertEqual(len(sent_kb.inline_keyboard[1]), 2)  # Sab, Dom
        self.assertIn("Lunedì", sent_kb.inline_keyboard[0][0].text)
        self.assertIn("Mercoledì", sent_kb.inline_keyboard[0][1].text)
        self.assertIn("Venerdì", sent_kb.inline_keyboard[0][2].text)
        self.assertIn("Sabato", sent_kb.inline_keyboard[1][0].text)
        self.assertIn("Domenica", sent_kb.inline_keyboard[1][1].text)

    # 6. Schedule toggle callback
    async def test_schedule_toggle_callback(self):
        sched_id = db.insert_scheduled_event(
            title="Serata GdT",
            text="Testo evento",
            schedule_days=["Lunedì"]
        )

        update = MagicMock()
        update.callback_query.data = f"sched_toggle_{sched_id}_mer"
        update.callback_query.message.chat_id = 999
        update.callback_query.from_user.id = 123
        update.callback_query.message.photo = None
        update.callback_query.message.edit_text = AsyncMock()
        update.callback_query.answer = AsyncMock()

        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await handle_callback_query(update, context)

        ev = db.get_scheduled_event(sched_id)
        self.assertIn("Mercoledì", ev["schedule_days"])
        self.assertIn("Lunedì", ev["schedule_days"])

        # Toggle again to deactivate Mercoledì
        update.callback_query.data = f"sched_toggle_{sched_id}_mer"
        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await handle_callback_query(update, context)

        ev = db.get_scheduled_event(sched_id)
        self.assertNotIn("Mercoledì", ev["schedule_days"])
        self.assertIn("Lunedì", ev["schedule_days"])

    # 7. 10:00 AM daily scheduler job
    async def test_send_daily_scheduled_reposts_job(self):
        now = datetime.now()
        days_it = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
        today_weekday = days_it[now.weekday()]

        sched_id = db.insert_scheduled_event(
            title="Evento Ricorrente Oggi",
            text="Titolo: Evento Ricorrente Oggi\nPosti: 4/4",
            schedule_days=[today_weekday]
        )

        bot = MagicMock()
        bot.send_message = AsyncMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await send_daily_scheduled_reposts(bot)

        bot.send_message.assert_called_once()
        msg_text = bot.send_message.call_args[1]["text"]
        self.assertIn(f"/event_repost_invoke {sched_id}", msg_text)
        self.assertIn("/event_repost_update", msg_text)
        self.assertIn("Evento Ricorrente Oggi", msg_text)

    # 8. /event_repost_invoke
    async def test_event_repost_invoke_command(self):
        sched_id = db.insert_scheduled_event(
            title="Cyberpunk Red",
            text="Titolo: Cyberpunk Red\nData: 01-01-2026\nPosti: 3/3\nDescrizione: Missione a Night City",
            schedule_days=["Lunedì"],
            specific_date="01-01-2026 21:00"
        )

        update = MagicMock()
        update.effective_chat.id = 999
        update.message.text = f"/event_repost_invoke {sched_id}"
        update.message.caption = None
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.extraction.parse_event_message", return_value={
                 "is_event": True,
                 "title": "Cyberpunk Red",
                 "date": "01-01-2026 21:00",
                 "normalized_date": "01-01-2026",
                 "system": "Cyberpunk Red",
                 "host": "Fixer",
                 "seats": "3/3",
                 "max_seats": 3,
                 "booked_seats": 0,
                 "description": "Missione a Night City"
             }):
            await event_repost_invoke_command(update, context)

        update.message.reply_text.assert_called()
        self.assertIn("invocato e pronto per la revisione", update.message.reply_text.call_args[0][0])

        upcoming = db.get_upcoming_events(include_today=True)
        today_norm = datetime.now().strftime("%d-%m-%Y")
        created_event = [e for e in upcoming if e["title"] == "Cyberpunk Red"][0]
        self.assertEqual(created_event["normalized_date"], today_norm)

    # 9. /event_repost_update
    async def test_event_repost_update_command(self):
        sched_id = db.insert_scheduled_event(
            title="Vecchio Titolo",
            text="Vecchio Testo",
            schedule_days=["Lunedì"]
        )

        update = MagicMock()
        update.effective_chat.id = 999

        reply_msg = MagicMock()
        reply_msg.text = "Nuovo Titolo Superfigo\nDescrizione aggiornata"
        reply_msg.caption = None
        reply_msg.photo = None
        reply_msg.document = None
        reply_msg.reply_markup = None

        update.message.reply_to_message = reply_msg
        update.message.text = f"/event_repost_update {sched_id}"
        update.message.caption = None
        update.message.photo = None
        update.message.document = None
        update.message.reply_text = AsyncMock()

        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await event_repost_update_command(update, context)

        update.message.reply_text.assert_called()
        self.assertIn("aggiornato con successo", update.message.reply_text.call_args[0][0])

        ev = db.get_scheduled_event(sched_id)
        self.assertEqual(ev["title"], "Nuovo Titolo Superfigo")
        self.assertEqual(ev["text"], "Nuovo Titolo Superfigo\nDescrizione aggiornata")

    # 10. /event_repost_list empty
    async def test_event_repost_list_empty(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.effective_user.id = 123
        update.effective_user.username = "testadmin"
        update.message.reply_text = AsyncMock()

        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await event_repost_list_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Nessun evento programmato", update.message.reply_text.call_args[0][0])

    # 11. /event_repost_list with events
    async def test_event_repost_list_with_events(self):
        sched_id1 = db.insert_scheduled_event(
            title="D&D Notturno",
            text="Testo D&D",
            schedule_days=["Lunedì", "Venerdì"]
        )
        sched_id2 = db.insert_scheduled_event(
            title="Call of Cthulhu One-Shot",
            text="Testo CoC",
            specific_date="15-10-2026 21:00"
        )

        update = MagicMock()
        update.effective_chat.id = 999
        update.effective_user.id = 123
        update.effective_user.username = "testadmin"
        update.message.reply_text = AsyncMock()

        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await event_repost_list_command(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("D&amp;D Notturno", text)
        self.assertIn(f"/event_repost_invoke {sched_id1}", text)
        self.assertIn("Call of Cthulhu One-Shot", text)
        self.assertIn(f"/event_repost_invoke {sched_id2}", text)
        self.assertIn("/event_repost_update", text)


if __name__ == "__main__":
    unittest.main()


