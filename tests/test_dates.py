from datetime import date, datetime
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import core.db as db
from core import config
from bot.handlers.edit import event_edit_command
from bot.handlers.extraction import handle_event_extraction
from bot.handlers.recap import manual_recap_command
from core.scheduler.recap import generate_daily_recap
from core.scheduler.archive import archive_today_images
from utils.date_utils import (
    parse_user_date,
    format_standard_event_date,
    validate_event_date_anomalies,
)
from utils.image_utils import move_image_locally


class TestDateUtils(unittest.TestCase):
    def test_parse_user_date_valid(self):
        # Without time (dash)
        dt, has_time = parse_user_date("05-09-2026")
        self.assertEqual(dt, datetime(2026, 9, 5, 0, 0))
        self.assertFalse(has_time)

        # Without time (slash, single digits)
        dt, has_time = parse_user_date("5/9/2026")
        self.assertEqual(dt, datetime(2026, 9, 5, 0, 0))
        self.assertFalse(has_time)

        # With time (dash)
        dt, has_time = parse_user_date("05-09-2026 21:30")
        self.assertEqual(dt, datetime(2026, 9, 5, 21, 30))
        self.assertTrue(has_time)

        # With time (slash)
        dt, has_time = parse_user_date("05/09/2026 20:00")
        self.assertEqual(dt, datetime(2026, 9, 5, 20, 0))
        self.assertTrue(has_time)

    def test_parse_user_date_invalid(self):
        self.assertIsNone(parse_user_date("invalid_date_text"))
        self.assertIsNone(parse_user_date("tomorrow"))
        self.assertIsNone(parse_user_date("31-02-2026"))  # Invalid day in Feb
        self.assertIsNone(parse_user_date("05-13-2026"))  # Month 13
        self.assertIsNone(parse_user_date("05-09-2026 25:00"))  # Hour 25
        self.assertIsNone(parse_user_date(""))
        self.assertIsNone(parse_user_date(None))

    def test_parse_user_date_keywords(self):
        # Suppose reference date is Wednesday 2026-10-07
        ref_dt = datetime(2026, 10, 7, 10, 0)  # Wednesday (weekday 2)

        # "oggi" without time
        dt, has_time = parse_user_date("oggi", reference_date=ref_dt)
        self.assertEqual(dt, datetime(2026, 10, 7, 0, 0))
        self.assertFalse(has_time)

        # "oggi" with time
        dt, has_time = parse_user_date("oggi 21:00", reference_date=ref_dt)
        self.assertEqual(dt, datetime(2026, 10, 7, 21, 0))
        self.assertTrue(has_time)

        # "MER" when today is Wednesday -> next Wednesday (14 Oct 2026)
        dt, has_time = parse_user_date("MER", reference_date=ref_dt)
        self.assertEqual(dt, datetime(2026, 10, 14, 0, 0))
        self.assertFalse(has_time)

        # "VEN" when today is Wednesday -> this Friday (9 Oct 2026)
        dt, has_time = parse_user_date("VEN 21:30", reference_date=ref_dt)
        self.assertEqual(dt, datetime(2026, 10, 9, 21, 30))
        self.assertTrue(has_time)

        # "LUN" when today is Wednesday -> next Monday (12 Oct 2026)
        dt, has_time = parse_user_date("LUN", reference_date=ref_dt)
        self.assertEqual(dt, datetime(2026, 10, 12, 0, 0))
        self.assertFalse(has_time)

        # Edge case: today is Monday (2026-10-05) and user inputs "LUN"
        monday_dt = datetime(2026, 10, 5, 12, 0)
        dt, has_time = parse_user_date("LUN", reference_date=monday_dt)
        self.assertEqual(dt, datetime(2026, 10, 12, 0, 0))  # Next Monday (+7 days)
        self.assertFalse(has_time)

    def test_format_standard_event_date(self):
        # Sept 5, 2026 is Saturday (Sabato)
        dt = datetime(2026, 9, 5, 21, 0)
        disp, norm = format_standard_event_date(dt, has_time=True)
        self.assertEqual(disp, "Sabato 05-09-2026 21:00")
        self.assertEqual(norm, "05-09-2026")

        # Sept 4, 2026 is Friday (Venerdì)
        dt2 = datetime(2026, 9, 4, 0, 0)
        disp2, norm2 = format_standard_event_date(dt2, has_time=False)
        self.assertEqual(disp2, "Venerdì 04-09-2026")
        self.assertEqual(norm2, "04-09-2026")

    def test_validate_event_date_anomalies_future_valid(self):
        # Sept 4, 2026 is Friday
        ev = {"date": "Venerdì 04-09-2026 21:00", "normalized_date": "04-09-2026"}
        warnings = validate_event_date_anomalies(ev, reference_date=date(2026, 9, 1))
        self.assertEqual(warnings, [])

    def test_validate_event_date_anomalies_past_date(self):
        ev = {"date": "Lunedì 01-01-2024", "normalized_date": "01-01-2024"}
        warnings = validate_event_date_anomalies(ev, reference_date=date(2026, 9, 1))
        self.assertTrue(any("PASSATO" in w for w in warnings))

    def test_validate_event_date_anomalies_weekday_mismatch_italian(self):
        # Sept 4, 2026 is Friday, but date string says 'Sabato'
        ev = {"date": "Sabato 04-09-2026 21:00", "normalized_date": "04-09-2026"}
        warnings = validate_event_date_anomalies(ev, reference_date=date(2026, 9, 1))
        self.assertTrue(any("Incongruenza data/giorno" in w for w in warnings))
        self.assertTrue(any("Sabato" in w and "Venerdì" in w for w in warnings))

    def test_validate_event_date_anomalies_weekday_mismatch_english(self):
        # Sept 4, 2026 is Friday, but date string says 'Saturday'
        ev = {"date": "Saturday 04 September 2026", "normalized_date": "04-09-2026"}
        warnings = validate_event_date_anomalies(ev, reference_date=date(2026, 9, 1))
        self.assertTrue(any("Incongruenza data/giorno" in w for w in warnings))
        self.assertTrue(any("Sabato" in w and "Venerdì" in w for w in warnings))

    def test_validate_event_date_anomalies_unparseable(self):
        ev = {"date": "data da definirsi", "normalized_date": ""}
        warnings = validate_event_date_anomalies(ev)
        self.assertTrue(any("Impossibile determinare una data valida" in w for w in warnings))

    def test_move_image_locally(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_dir = os.path.join(temp_dir, "2026", "09", "08")
            os.makedirs(old_dir, exist_ok=True)
            img_path = os.path.join(old_dir, "test.jpg")
            with open(img_path, "w") as f:
                f.write("data")

            # Move to new date
            new_path = move_image_locally(img_path, temp_dir, "09-09-2026")
            expected_path = os.path.join(temp_dir, "2026", "09", "09", "test.jpg")
            self.assertEqual(new_path, expected_path)
            self.assertTrue(os.path.exists(expected_path))
            self.assertFalse(os.path.exists(img_path))
            # Verify old empty dir is cleaned up
            self.assertFalse(os.path.exists(old_dir))

            # Move same path -> noop
            same_path = move_image_locally(new_path, temp_dir, "09-09-2026")
            self.assertEqual(same_path, expected_path)

            # Move non-existent file -> None
            self.assertIsNone(move_image_locally("/non/existent/file.jpg", temp_dir, "09-09-2026"))
            self.assertIsNone(move_image_locally(None, temp_dir, "09-09-2026"))


class TestDateEditingAndValidation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events_date.db")
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = self.test_db_path
        db.init_db()

        self.event_data = {
            "title": "Tavolo GdR",
            "date": "Venerdì 04-09-2026 21:00",
            "normalized_date": "04-09-2026",
            "system": "D&D 5e",
            "host": "Master DM",
            "seats": "4/4",
            "max_seats": 4,
            "booked_seats": 0,
            "status": "pending",
        }
        self.event_id = db.insert_event(
            self.event_data,
            image_path=None,
            original_text="Raw text",
            message_link="https://t.me/c/123/1",
            telegram_message_id=5001,
        )

    def tearDown(self):
        config.DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()

    async def test_event_edit_date_invalid_format_rejects(self):
        update = MagicMock()
        update.effective_chat.id = 999
        reply_msg = MagicMock()
        reply_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        reply_msg.caption = None
        reply_msg.text = "Event caption"
        reply_msg.photo = False
        update.message.reply_to_message = reply_msg
        update.message.reply_text = AsyncMock()
        update.message.text = "/event_edit_date domani sera"
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await event_edit_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Formato data non valido", update.message.reply_text.call_args[0][0])
        ev = db.get_event(self.event_id)
        # Event in DB must NOT be changed
        self.assertEqual(ev["date"], "Venerdì 04-09-2026 21:00")
        self.assertEqual(ev["normalized_date"], "04-09-2026")

    async def test_event_edit_date_nonexistent_calendar_date_rejects(self):
        update = MagicMock()
        update.effective_chat.id = 999
        reply_msg = MagicMock()
        reply_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        reply_msg.caption = None
        reply_msg.text = "Event caption"
        reply_msg.photo = False
        update.message.reply_to_message = reply_msg
        update.message.reply_text = AsyncMock()
        update.message.text = "/event_edit_date 31-02-2026"
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await event_edit_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Formato data non valido", update.message.reply_text.call_args[0][0])
        ev = db.get_event(self.event_id)
        self.assertEqual(ev["normalized_date"], "04-09-2026")

    async def test_event_edit_date_valid_dual_sync(self):
        update = MagicMock()
        update.effective_chat.id = 999
        reply_msg = MagicMock()
        reply_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        reply_msg.caption = None
        reply_msg.text = "Event caption"
        reply_msg.photo = False
        reply_msg.edit_text = AsyncMock()
        update.message.reply_to_message = reply_msg
        update.message.reply_text = AsyncMock()
        # Sept 5, 2026 is Saturday (Sabato)
        update.message.text = "/event_edit_date 05-09-2026 21:00"
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.edit.update_event_messages", AsyncMock()):
            await event_edit_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("aggiornato con successo", update.message.reply_text.call_args[0][0])
        ev = db.get_event(self.event_id)
        # Date must have Italian weekday prepended and normalized_date synced
        self.assertEqual(ev["date"], "Sabato 05-09-2026 21:00")
        self.assertEqual(ev["normalized_date"], "05-09-2026")
        reply_msg.edit_text.assert_called_once()

    async def test_event_edit_date_moves_image_and_updates_db(self):
        old_dir = os.path.join(self.temp_dir.name, "2026", "09", "04")
        os.makedirs(old_dir, exist_ok=True)
        img_file = os.path.join(old_dir, "event_test_1.jpg")
        with open(img_file, "wb") as f:
            f.write(b"test image data 1")

        db.update_event_field(self.event_id, "image_path", img_file)

        update = MagicMock()
        update.effective_chat.id = 999
        reply_msg = MagicMock()
        reply_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        reply_msg.caption = None
        reply_msg.text = "Event caption"
        reply_msg.photo = False
        reply_msg.edit_text = AsyncMock()
        update.message.reply_to_message = reply_msg
        update.message.reply_text = AsyncMock()
        update.message.text = "/event_edit_date 09-09-2026 21:00"
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("core.config.DATA_DIR", self.temp_dir.name), \
             patch("bot.handlers.edit.update_event_messages", AsyncMock()):
            await event_edit_command(update, context)

        ev = db.get_event(self.event_id)
        expected_new_path = os.path.join(self.temp_dir.name, "2026", "09", "09", "event_test_1.jpg")
        self.assertEqual(ev["image_path"], expected_new_path)
        self.assertTrue(os.path.exists(expected_new_path))
        self.assertFalse(os.path.exists(img_file))
        self.assertFalse(os.path.exists(old_dir))

    async def test_handle_event_extraction_past_date_warning_shown(self):
        parsed_past = {
            "is_event": True,
            "title": "Vecchio Evento",
            "date": "01-01-2024",
            "normalized_date": "01-01-2024",
            "system": "OSR",
            "host": "Old Master",
            "seats": "3/3",
            "max_seats": 3,
        }
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        with patch("bot.handlers.extraction.parse_event_message", return_value=parsed_past), \
             patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("utils.date_utils.date") as mock_date:
            mock_date.today.return_value = date(2026, 9, 1)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

            await handle_event_extraction(
                text="Evento 01-01-2024",
                image_bytes=None,
                context=context,
                is_manual_trigger=True,
            )

        context.bot.send_message.assert_called_once()
        sent_text = context.bot.send_message.call_args.kwargs.get("text", "")
        self.assertIn("🚨 ATTENZIONE ANOMALIE DATA:", sent_text)
        self.assertIn("PASSATO", sent_text)

    async def test_handle_event_extraction_weekday_mismatch_warning_shown(self):
        # Sept 4, 2026 is Friday, but date says "Sabato 04-09-2026"
        parsed_mismatch = {
            "is_event": True,
            "title": "Evento Sabato",
            "date": "Sabato 04-09-2026",
            "normalized_date": "04-09-2026",
            "system": "OSR",
            "host": "Master",
            "seats": "3/3",
            "max_seats": 3,
        }
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        with patch("bot.handlers.extraction.parse_event_message", return_value=parsed_mismatch), \
             patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("utils.date_utils.date") as mock_date:
            mock_date.today.return_value = date(2026, 9, 1)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

            await handle_event_extraction(
                text="Evento Sabato 04-09-2026",
                image_bytes=None,
                context=context,
                is_manual_trigger=True,
            )

        context.bot.send_message.assert_called_once()
        sent_text = context.bot.send_message.call_args.kwargs.get("text", "")
        self.assertIn("🚨 ATTENZIONE ANOMALIE DATA:", sent_text)
        self.assertIn("Incongruenza data/giorno", sent_text)
        self.assertIn("Sabato", sent_text)
        self.assertIn("Venerdì", sent_text)

    async def test_event_edit_date_clears_date_anomaly_warning(self):
        # Initial event has mismatch
        db.update_event_field(self.event_id, "date", "Sabato 04-09-2026")
        db.update_event_field(self.event_id, "normalized_date", "04-09-2026")

        update = MagicMock()
        update.effective_chat.id = 999
        reply_msg = MagicMock()
        reply_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        reply_msg.caption = None
        reply_msg.text = "🚨 ATTENZIONE ANOMALIE DATA:\n..."
        reply_msg.photo = False
        reply_msg.edit_text = AsyncMock()
        update.message.reply_to_message = reply_msg
        update.message.reply_text = AsyncMock()

        # Admin corrects date to a valid future date
        update.message.text = "/event_edit_date 04-09-2026 21:00"
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.edit.update_event_messages", AsyncMock()), \
             patch("utils.date_utils.date") as mock_date:
            mock_date.today.return_value = date(2026, 9, 1)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

            await event_edit_command(update, context)

        reply_msg.edit_text.assert_called_once()
        edited_text = reply_msg.edit_text.call_args.kwargs.get("text", "")
        # Warning must be completely gone
        self.assertNotIn("🚨 ATTENZIONE ANOMALIE DATA:", edited_text)
        self.assertIn("Data: Venerdì 04-09-2026 21:00", edited_text)

    async def test_manual_recap_command_no_events_today(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.message.message_id = 777
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = []
        context.bot.send_message = AsyncMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("core.config.ADMIN_CHAT_ID", "999"):
            await manual_recap_command(update, context)

        context.bot.send_message.assert_called_once()
        call_kwargs = context.bot.send_message.call_args.kwargs
        self.assertEqual(call_kwargs["chat_id"], "999")
        self.assertEqual(call_kwargs["text"], "Nessun evento in programma per oggi.")
        self.assertEqual(call_kwargs["reply_to_message_id"], 777)
        update.message.reply_text.assert_not_called()

    async def test_manual_recap_command_no_events_reply_exception_fallback(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.message.message_id = 777
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = []
        context.bot.send_message = AsyncMock(side_effect=[Exception("Message not found"), None])

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("core.config.ADMIN_CHAT_ID", "999"):
            await manual_recap_command(update, context)

        # First attempt with reply_to_message_id failed, second fallback attempt without it succeeded
        self.assertEqual(context.bot.send_message.call_count, 2)
        fallback_kwargs = context.bot.send_message.call_args.kwargs
        self.assertEqual(fallback_kwargs["chat_id"], "999")
        self.assertEqual(fallback_kwargs["text"], "Nessun evento in programma per oggi.")
        self.assertNotIn("reply_to_message_id", fallback_kwargs)

    async def test_manual_recap_command_no_events_specific_date(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.message.message_id = 778
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = ["15-09-2026"]
        context.bot.send_message = AsyncMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("core.config.ADMIN_CHAT_ID", "999"):
            await manual_recap_command(update, context)

        context.bot.send_message.assert_called_once()
        call_kwargs = context.bot.send_message.call_args.kwargs
        self.assertEqual(call_kwargs["chat_id"], "999")
        self.assertEqual(call_kwargs["text"], "Nessun evento in programma per la data 15-09-2026.")
        self.assertEqual(call_kwargs["reply_to_message_id"], 778)
        update.message.reply_text.assert_not_called()

    async def test_manual_recap_command_invalid_date_format(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = ["not-a-valid-date"]

        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await manual_recap_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Formato data non valido", update.message.reply_text.call_args[0][0])

    async def test_manual_recap_command_with_events_today(self):
        today_str = datetime.now().strftime("%d-%m-%Y")
        today_ev = {
            "title": "Partita di Oggi",
            "date": "Oggi 21:00",
            "normalized_date": today_str,
            "system": "Pathfinder",
            "host": "Master Luke",
            "seats": "3/4",
            "booked_seats": 1,
            "max_seats": 4,
            "description": "Avventura serale",
            "status": "approved",
            "image_path": None,
        }
        ev_id = db.insert_event(today_ev, None, "test text")
        db.update_event_status(ev_id, "approved")

        update = MagicMock()
        update.effective_chat.id = 999
        update.message.message_id = 888
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = []
        context.bot.send_message = AsyncMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("core.scheduler.recap.create_collage", return_value=None):
            await manual_recap_command(update, context)

        context.bot.send_message.assert_called_once()
        recap_call_kwargs = context.bot.send_message.call_args.kwargs
        self.assertEqual(recap_call_kwargs["chat_id"], "999")
        self.assertIn("Partita di Oggi", recap_call_kwargs["text"])
        update.message.reply_text.assert_called_once_with("Recap generato per la data: Oggi")

    async def test_generate_daily_recap_automatic_silent_when_no_events(self):
        bot = MagicMock()
        bot.send_message = AsyncMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("core.scheduler.recap.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 0
            mock_now.strftime.side_effect = lambda fmt: "01-01-2099" if "%d" in fmt else "Monday"
            mock_dt.now.return_value = mock_now

            res = await generate_daily_recap(bot, is_manual=False)

        self.assertFalse(res)
        bot.send_message.assert_not_called()

    async def test_archive_today_images_disables_booking_for_today_events(self):
        today_str = datetime.now().strftime("%d-%m-%Y")
        tomorrow_str = "30-12-2099"

        # Today's approved event with channel and discussion messages
        ev1_id = db.insert_event({
            "title": "Evento Oggi",
            "date": f"Oggi {today_str}",
            "normalized_date": today_str,
            "system": "D&D",
            "host": "Master",
            "seats": "4/4",
            "booked_seats": 0,
            "max_seats": 4,
            "description": "Descrizione",
        }, None, "raw 1")
        db.update_event_status(ev1_id, "approved")
        db.update_telegram_message_info(ev1_id, 1001, "https://t.me/c/123/1001")
        db.update_discussion_message_info(ev1_id, 2001, "-100999999")

        # Tomorrow's approved event
        ev2_id = db.insert_event({
            "title": "Evento Futuro",
            "date": f"Domani {tomorrow_str}",
            "normalized_date": tomorrow_str,
            "system": "Pathfinder",
            "host": "Master 2",
            "seats": "4/4",
            "booked_seats": 0,
            "max_seats": 4,
            "description": "Descrizione",
        }, None, "raw 2")
        db.update_event_status(ev2_id, "approved")
        db.update_telegram_message_info(ev2_id, 1002, "https://t.me/c/123/1002")
        db.update_discussion_message_info(ev2_id, 2002, "-100999999")

        bot = MagicMock()
        bot.edit_message_reply_markup = AsyncMock()

        with patch("core.config.PUBLIC_CHANNEL_ID", "-100123456"), \
             patch("core.config.DISCUSSION_GROUP_ID", "-100999999"):
            await archive_today_images(bot=bot)

        calls = bot.edit_message_reply_markup.call_args_list
        edited_msgs = [c.kwargs.get("message_id") for c in calls]
        self.assertIn(1001, edited_msgs)
        self.assertIn(2001, edited_msgs)
        self.assertNotIn(1002, edited_msgs)
        self.assertNotIn(2002, edited_msgs)

        for c in calls:
            self.assertIsNone(c.kwargs.get("reply_markup"))

    async def test_archive_today_images_without_bot_succeeds(self):
        await archive_today_images(bot=None)




if __name__ == "__main__":
    unittest.main()
