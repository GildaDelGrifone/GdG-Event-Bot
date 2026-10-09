import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import core.db as db
from core import config
from core.ai_parser import parse_event_message
from utils.templates import format_public_event_message, format_instagram_story


class TestRoleplayTypeFormatting(unittest.TestCase):
    def test_format_public_event_message_rpg(self):
        event_rpg = {
            "title": "D&D Session",
            "date": "05-09-2026 21:00",
            "system": "D&D 5e",
            "host": "Matt Mercer",
            "max_seats": 5,
            "booked_seats": 2,
            "is_roleplay": 1,
        }
        text = format_public_event_message(event_rpg)
        self.assertIn("👑 Master: Matt Mercer", text)
        self.assertNotIn("👑 Host:", text)

    def test_format_public_event_message_non_rpg(self):
        event_boardgame = {
            "title": "Catan Night",
            "date": "05-09-2026 21:00",
            "system": "Settlers of Catan",
            "host": "Klaus",
            "max_seats": 4,
            "booked_seats": 1,
            "is_roleplay": 0,
        }
        text = format_public_event_message(event_boardgame)
        self.assertIn("👑 Host: Klaus", text)
        self.assertNotIn("👑 Master:", text)

    def test_format_public_event_message_default_fallback(self):
        event_no_flag = {
            "title": "Boardgame",
            "host": "Admin",
        }
        text = format_public_event_message(event_no_flag)
        self.assertIn("👑 Host: Admin", text)

    def test_format_public_event_message_bold_title_and_plain_details(self):
        event = {
            "title": "D&D Session",
            "date": "05-09-2026 21:00",
            "system": "D&D 5e",
            "host": "Matt Mercer",
            "max_seats": 5,
            "booked_seats": 2,
            "extra_info": "Portare dadi e scheda",
            "description": "Avventura epica",
        }
        text = format_public_event_message(event)
        # Title must use <b> and not **
        self.assertIn("📣 <b>D&amp;D Session</b>", text)
        self.assertNotIn("**", text)
        # Details label must not have ** and must not be bolded
        self.assertIn("\n🏷️ Dettagli:\nPortare dadi e scheda\n", text)
        self.assertNotIn("<b>Dettagli:</b>", text)
        self.assertNotIn("**Dettagli:**", text)

    def test_format_public_event_message_cancelled_bold(self):
        event = {
            "title": "Game Night",
            "status": "cancelled",
            "max_seats": 4,
            "extra_info": "Info extra",
        }
        text = format_public_event_message(event)
        self.assertIn("📣 <b>❌ [ANNULLATO] Game Night</b>", text)
        self.assertNotIn("**", text)
        self.assertIn("\n🏷️ Dettagli:\nInfo extra\n", text)

    def test_format_instagram_story_rpg(self):
        event_rpg = {
            "title": "Call of Cthulhu",
            "date": "06-09-2026",
            "system": "CoC 7e",
            "host": "Lovecraft",
            "max_seats": 4,
            "is_roleplay": True,
        }
        text = format_instagram_story(event_rpg)
        self.assertIn("Master: Lovecraft", text)
        self.assertNotIn("Host: Lovecraft", text)

    def test_format_instagram_story_non_rpg(self):
        event_boardgame = {
            "title": "Terraforming Mars",
            "date": "06-09-2026",
            "system": "Board Game",
            "host": "Elon",
            "max_seats": 5,
            "is_roleplay": False,
        }
        text = format_instagram_story(event_boardgame)
        self.assertIn("Host: Elon", text)
        self.assertNotIn("Master: Elon", text)


class TestRoleplayTypeDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = self.test_db_path
        db.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()
        config.DB_PATH = self.orig_db_path

    def test_insert_and_get_is_roleplay(self):
        ev_rpg = {
            "title": "Cyberpunk Red",
            "host": "Mike",
            "is_roleplay": True,
        }
        ev_id = db.insert_event(ev_rpg, None, "Cyberpunk Red raw")
        stored = db.get_event(ev_id)
        self.assertEqual(stored["is_roleplay"], 1)

        ev_bg = {
            "title": "Wingspan",
            "host": "Elizabeth",
            "is_roleplay": False,
        }
        ev_bg_id = db.insert_event(ev_bg, None, "Wingspan raw")
        stored_bg = db.get_event(ev_bg_id)
        self.assertEqual(stored_bg["is_roleplay"], 0)

    def test_update_event_field_is_roleplay(self):
        ev = {
            "title": "Game Night",
            "host": "Alex",
            "is_roleplay": 0,
        }
        ev_id = db.insert_event(ev, None, "Game Night raw")
        self.assertEqual(db.get_event(ev_id)["is_roleplay"], 0)

        success = db.update_event_field(ev_id, "is_roleplay", 1)
        self.assertTrue(success)
        self.assertEqual(db.get_event(ev_id)["is_roleplay"], 1)

        success = db.update_event_field(ev_id, "is_roleplay", 0)
        self.assertTrue(success)
        self.assertEqual(db.get_event(ev_id)["is_roleplay"], 0)

    def test_init_db_migrates_is_roleplay_column(self):
        import sqlite3
        legacy_db_path = os.path.join(self.temp_dir.name, "legacy_events.db")
        with sqlite3.connect(legacy_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    date TEXT
                )
            ''')
            conn.commit()

        orig = config.DB_PATH
        try:
            config.DB_PATH = legacy_db_path
            db.init_db()
            with sqlite3.connect(legacy_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(events)")
                cols = [c[1] for c in cursor.fetchall()]
                self.assertIn("is_roleplay", cols)
        finally:
            config.DB_PATH = orig


class TestEventEditTypeCommand(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = self.test_db_path
        db.init_db()

        self.event_id = db.insert_event({
            "title": "Session 1",
            "date": "05-09-2026 21:00",
            "system": "Generic",
            "host": "Master DM",
            "is_roleplay": 1,
        }, None, "raw text")
        db.update_event_status(self.event_id, "approved")

    def tearDown(self):
        self.temp_dir.cleanup()
        config.DB_PATH = self.orig_db_path

    async def test_event_edit_type_to_boardgame(self):
        from bot.handlers.edit import event_edit_command

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = "/event_edit_type boardgame"
        update.message.caption = None
        update.message.reply_text = AsyncMock()

        target_msg = MagicMock()
        target_msg.photo = False
        target_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        target_msg.edit_text = AsyncMock()
        update.message.reply_to_message = target_msg
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.edit.update_event_messages", AsyncMock()) as mock_update_msgs:
            await event_edit_command(update, context)

        ev = db.get_event(self.event_id)
        self.assertEqual(ev["is_roleplay"], 0)
        update.message.reply_text.assert_called_with("✅ Campo 'is_roleplay' aggiornato con successo!")
        mock_update_msgs.assert_called_once()
        target_msg.edit_text.assert_called_once()
        self.assertIn("Host: Master DM", target_msg.edit_text.call_args.kwargs["text"])

    async def test_event_edit_type_to_rpg(self):
        from bot.handlers.edit import event_edit_command

        db.update_event_field(self.event_id, "is_roleplay", 0)

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = "/event_edit_type rpg"
        update.message.caption = None
        update.message.reply_text = AsyncMock()

        target_msg = MagicMock()
        target_msg.photo = False
        target_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        target_msg.edit_text = AsyncMock()
        update.message.reply_to_message = target_msg
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.edit.update_event_messages", AsyncMock()):
            await event_edit_command(update, context)

        ev = db.get_event(self.event_id)
        self.assertEqual(ev["is_roleplay"], 1)
        self.assertIn("Master: Master DM", target_msg.edit_text.call_args.kwargs["text"])

    async def test_event_edit_type_toggle(self):
        from bot.handlers.edit import event_edit_command

        self.assertEqual(db.get_event(self.event_id)["is_roleplay"], 1)

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = "/event_edit_type"
        update.message.caption = None
        update.message.reply_text = AsyncMock()

        target_msg = MagicMock()
        target_msg.photo = False
        target_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        target_msg.edit_text = AsyncMock()
        update.message.reply_to_message = target_msg
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.edit.update_event_messages", AsyncMock()):
            await event_edit_command(update, context)

        ev = db.get_event(self.event_id)
        self.assertEqual(ev["is_roleplay"], 0)

    async def test_event_edit_type_invalid_argument(self):
        from bot.handlers.edit import event_edit_command

        update = MagicMock()


class TestAiParserRoleplayDetection(unittest.TestCase):
    def test_parse_event_message_extracts_is_roleplay(self):
        mock_response = MagicMock()
        mock_response.text = '''```json
        {
            "is_event": true,
            "title": "Sine Requie: Terre Perdute",
            "date": "05-09-2026 21:00",
            "normalized_date": "05-09-2026",
            "system": "Sine Requie",
            "host": "Cartomante",
            "seats": "4/4",
            "max_seats": 4,
            "booked_seats": 0,
            "is_roleplay": true,
            "extra_info": "",
            "description": "Una terra oscura"
        }
        ```'''

        with patch("core.ai_parser.genai.GenerativeModel") as mock_model_cls:
            mock_model = MagicMock()
            mock_model.generate_content.return_value = mock_response
            mock_model_cls.return_value = mock_model

            res = parse_event_message("Test Sine Requie message")
            self.assertIsNotNone(res)
            self.assertTrue(res["is_roleplay"])

    def test_parse_event_message_extracts_is_roleplay_false(self):
        mock_response = MagicMock()
        mock_response.text = '''```json
        {
            "is_event": true,
            "title": "Arkham Horror LCG",
            "date": "05-09-2026 21:00",
            "normalized_date": "05-09-2026",
            "system": "Card Game",
            "host": "Investigatore",
            "seats": "3/3",
            "max_seats": 3,
            "booked_seats": 0,
            "is_roleplay": false,
            "extra_info": "",
            "description": "Campagna Arkham"
        }
        ```'''

        with patch("core.ai_parser.genai.GenerativeModel") as mock_model_cls:
            mock_model = MagicMock()
            mock_model.generate_content.return_value = mock_response
            mock_model_cls.return_value = mock_model

            res = parse_event_message("Test Arkham message")
            self.assertIsNotNone(res)
            self.assertFalse(res["is_roleplay"])

