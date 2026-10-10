import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import core.db as db
from core import config
from bot.handlers.story import event_regenerate_story_command
from utils.templates import format_event_seats


class TestEventRegenerateStoryCommand(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_bot.db")
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = self.db_path
        db.init_db()

        self.event_id = db.insert_event({
            "title": "Terraforming Mars",
            "date": "Venerdì 20-10-2026",
            "normalized_date": "20-10-2026",
            "system": "Sci-Fi",
            "host": "Elon",
            "seats": "2/4",
            "booked_seats": 2,
            "max_seats": 4,
            "description": "Colonizziamo Marte",
            "extra_info": "",
            "is_roleplay": 0,
        }, None, "raw text")
        db.update_event_status(self.event_id, "approved")

    def tearDown(self):
        self.temp_dir.cleanup()
        config.DB_PATH = self.orig_db_path

    async def test_unauthorized_user_ignored(self):
        update = MagicMock()
        update.effective_chat.id = 11111
        update.message = MagicMock()
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await event_regenerate_story_command(update, context)

        update.message.reply_text.assert_not_called()

    async def test_no_reply_and_no_arg_shows_help(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = "/event_regenerate_story"
        update.message.caption = None
        update.message.reply_to_message = None
    async def test_reply_to_non_event_message_shows_error(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = "/event_regenerate_story"
        update.message.caption = None
        update.message.reply_text = AsyncMock()

        reply_msg = MagicMock()
        reply_msg.reply_markup = None
        reply_msg.text = "Just a casual message without event ID"
        reply_msg.caption = None
        reply_msg.message_id = 12345
        update.message.reply_to_message = reply_msg

        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await event_regenerate_story_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Rispondi al messaggio di un evento", update.message.reply_text.call_args[0][0])

    async def test_event_not_found_in_db(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = "/event_regenerate_story 99999"
        update.message.caption = None
        update.message.reply_to_message = None
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await event_regenerate_story_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Evento #99999 non trovato", update.message.reply_text.call_args[0][0])

    async def test_success_via_reply_to_event(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = "/event_regenerate_story"
        update.message.caption = None
        update.message.chat_id = 999

        status_msg = MagicMock()
        status_msg.delete = AsyncMock()
        status_msg.edit_text = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=status_msg)

        reply_msg = MagicMock()
        btn = MagicMock()
        btn.callback_data = f"publish_event_{self.event_id}"
        reply_msg.reply_markup.inline_keyboard = [[btn]]
        update.message.reply_to_message = reply_msg

        context = MagicMock()
        fake_story_path = os.path.join(self.temp_dir.name, "fake_story.jpg")
        with open(fake_story_path, "wb") as f:
            f.write(b"fake story image data")

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.story.create_story_image", return_value=fake_story_path) as mock_create, \
             patch("bot.handlers.story.send_image_or_error", new_callable=AsyncMock) as mock_send:

            await event_regenerate_story_command(update, context)

        mock_create.assert_called_once()
        mock_send.assert_called_once()
        send_args = mock_send.call_args
        self.assertEqual(send_args[0][1], 999)
        self.assertEqual(send_args[0][2], fake_story_path)
        self.assertIn(f"#{self.event_id}", send_args[1]["caption"])
        status_msg.delete.assert_called_once()

    async def test_success_via_id_argument(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = f"/event_regenerate_story {self.event_id}"
        update.message.caption = None
        update.message.reply_to_message = None
        update.message.chat_id = 999

        status_msg = MagicMock()
        status_msg.delete = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=status_msg)

        context = MagicMock()
        fake_story_path = os.path.join(self.temp_dir.name, "fake_story2.jpg")
        with open(fake_story_path, "wb") as f:
            f.write(b"fake story image data 2")

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.story.create_story_image", return_value=fake_story_path) as mock_create, \
             patch("bot.handlers.story.send_image_or_error", new_callable=AsyncMock) as mock_send:

            await event_regenerate_story_command(update, context)

        mock_create.assert_called_once()
        mock_send.assert_called_once()
        status_msg.delete.assert_called_once()

    async def test_story_generation_error(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = f"/event_regenerate_story {self.event_id}"
        update.message.caption = None
        update.message.reply_to_message = None
        update.message.chat_id = 999

        status_msg = MagicMock()
        status_msg.delete = AsyncMock()
        status_msg.edit_text = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=status_msg)

        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.story.create_story_image", return_value=None) as mock_create:

            await event_regenerate_story_command(update, context)

        mock_create.assert_called_once()
        status_msg.edit_text.assert_called_once()
        self.assertIn("Errore durante la generazione", status_msg.edit_text.call_args[0][0])


class TestFormatEventSeats(unittest.TestCase):

    def test_format_event_seats_limited(self):
        ev = {"booked_seats": 2, "max_seats": 5, "status": "approved"}
        self.assertEqual(format_event_seats(ev), "3/5")

    def test_format_event_seats_full(self):
        ev = {"booked_seats": 5, "max_seats": 5, "status": "approved"}
        self.assertEqual(format_event_seats(ev), "0/5 Completo")

    def test_format_event_seats_overbooked(self):
        ev = {"booked_seats": 6, "max_seats": 5, "status": "approved"}
        self.assertEqual(format_event_seats(ev), "0/5 Completo")

    def test_format_event_seats_unlimited(self):
        ev = {"booked_seats": 0, "max_seats": None, "status": "approved"}
        self.assertEqual(format_event_seats(ev), "Nessun limite")

        ev = {"booked_seats": 3, "max_seats": None, "status": "approved"}
        self.assertEqual(format_event_seats(ev), "Nessun limite (Prenotati: 3)")

    def test_format_event_seats_cancelled(self):
        ev = {"booked_seats": 2, "max_seats": 4, "status": "cancelled"}
        self.assertEqual(format_event_seats(ev), "0/4 [ANNULLATO]")

        ev = {"booked_seats": 2, "max_seats": None, "status": "cancelled"}
        self.assertEqual(format_event_seats(ev), "0 (Nessun limite) [ANNULLATO]")

