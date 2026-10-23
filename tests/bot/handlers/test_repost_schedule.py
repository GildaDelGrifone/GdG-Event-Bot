import unittest

import core.db as db
from bot.handlers.repost_schedule import (
    event_schedule_command,
    event_schedule_list_command,
    event_schedule_update_command,
)
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin
from tests.support.telegram import admin_update, make_context, make_message


def source_post(text, message_id=1):
    """The post an admin replies to with /event_schedule or /event_schedule_update."""
    message = make_message(text=text, message_id=message_id)
    message.reply_markup = None
    return message


class TestEventScheduleCommands(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_event_schedule_creates_scheduled_event_with_keyboard(self):
        reply_msg = source_post(
            "Titolo: Gioco da Tavolo\nData: 10-10-2026 21:00\nPosti: 4/4\nDescrizione: Serata Boardgame", 777)
        update = admin_update("/event_schedule", reply_to=reply_msg)

        with as_admin_chat():
            await event_schedule_command(update, make_context())

        update.message.reply_text.assert_called_once()
        sent_text = update.message.reply_text.call_args[0][0]
        sent_kb = update.message.reply_text.call_args[1]["reply_markup"]

        self.assertIn("Programmazione Repost Evento", sent_text)
        self.assertEqual(len(sent_kb.inline_keyboard), 4)  # days, days, advance, delete/close
        self.assertEqual(len(sent_kb.inline_keyboard[0]), 3)  # Lun, Mer, Ven
        self.assertEqual(len(sent_kb.inline_keyboard[1]), 2)  # Sab, Dom
        self.assertIn("Lunedì", sent_kb.inline_keyboard[0][0].text)
        self.assertIn("Mercoledì", sent_kb.inline_keyboard[0][1].text)
        self.assertIn("Venerdì", sent_kb.inline_keyboard[0][2].text)
        self.assertIn("Sabato", sent_kb.inline_keyboard[1][0].text)
        self.assertIn("Domenica", sent_kb.inline_keyboard[1][1].text)

    async def test_event_schedule_keyboard_has_advance_row(self):
        update = admin_update("/event_schedule", reply_to=source_post("Titolo: X\nPosti: 4/4", 778))
        with as_admin_chat():
            await event_schedule_command(update, make_context())
        row = update.message.reply_text.call_args[1]["reply_markup"].inline_keyboard[2]
        self.assertEqual([b.text for b in row], ["➖", "⏳ Anticipo: 0 gg", "➕"])

    async def test_event_schedule_new_with_date_and_advance(self):
        update = admin_update("/event_schedule 24-10-2026 21:00 2",
                              reply_to=source_post("Titolo: Serata\nPosti: 4/4", 779))
        with as_admin_chat():
            await event_schedule_command(update, make_context())
        ev = db.get_all_scheduled_events()[0]
        self.assertEqual((ev["specific_date"], ev["advance_days"]), ("Sabato 24-10-2026 21:00", 2))

    async def test_event_schedule_existing_advance_only_and_with_date(self):
        sched_id = db.insert_scheduled_event("T", "testo")
        update = admin_update(f"/event_schedule {sched_id} 3")
        with as_admin_chat():
            await event_schedule_command(update, make_context())
        ev = db.get_scheduled_event(sched_id)
        self.assertEqual((ev["advance_days"], ev["specific_date"]), (3, None))
        self.assertIn("anticipo aggiornati", update.message.reply_text.call_args[0][0])

        update = admin_update(f"/event_schedule {sched_id} 24-10-2026 21:00 1")
        with as_admin_chat():
            await event_schedule_command(update, make_context())
        ev = db.get_scheduled_event(sched_id)
        self.assertEqual((ev["advance_days"], ev["specific_date"]), (1, "Sabato 24-10-2026 21:00"))

    async def test_event_schedule_rejects_out_of_range_advance(self):
        sched_id = db.insert_scheduled_event("T", "testo")
        update = admin_update(f"/event_schedule {sched_id} 31")
        with as_admin_chat():
            await event_schedule_command(update, make_context())
        self.assertIn("tra 0 e 30", update.message.reply_text.call_args[0][0])
        self.assertEqual(db.get_scheduled_event(sched_id)["advance_days"], 0)

    async def test_event_schedule_update_command(self):
        sched_id = db.insert_scheduled_event(title="Vecchio Titolo", text="Vecchio Testo", schedule_days=["Lunedì"])
        update = admin_update(f"/event_schedule_update {sched_id}",
                              reply_to=source_post("Nuovo Titolo Superfigo\nDescrizione aggiornata"))

        with as_admin_chat():
            await event_schedule_update_command(update, make_context())

        update.message.reply_text.assert_called()
        self.assertIn("aggiornato con successo", update.message.reply_text.call_args[0][0])

        ev = db.get_scheduled_event(sched_id)
        self.assertEqual(ev["title"], "Nuovo Titolo Superfigo")
        self.assertEqual(ev["text"], "Nuovo Titolo Superfigo\nDescrizione aggiornata")

    async def test_event_schedule_list_empty(self):
        update = admin_update()

        with as_admin_chat():
            await event_schedule_list_command(update, make_context())

        update.message.reply_text.assert_called_once()
        self.assertIn("Nessun evento programmato", update.message.reply_text.call_args[0][0])

    async def test_event_schedule_list_with_events(self):
        sched_id1 = db.insert_scheduled_event(title="D&D Notturno", text="Testo D&D", schedule_days=["Lunedì", "Venerdì"])
        sched_id2 = db.insert_scheduled_event(title="Call of Cthulhu One-Shot", text="Testo CoC",
                                              specific_date="15-10-2026 21:00")
        update = admin_update()

        with as_admin_chat():
            await event_schedule_list_command(update, make_context())

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("D&amp;D Notturno", text)
        self.assertIn(f"/event_schedule_invoke {sched_id1}", text)
        self.assertIn("Call of Cthulhu One-Shot", text)
        self.assertIn(f"/event_schedule_invoke {sched_id2}", text)
        self.assertIn("/event_schedule_update", text)


if __name__ == "__main__":
    unittest.main()
