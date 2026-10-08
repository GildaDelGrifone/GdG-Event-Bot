import os
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import core.db as db
from core import config
from bot.event_generator.bgg import fetch_bgg_game_image
from bot.event_generator.ai import generate_event_data_with_ai
from bot.event_generator.pipeline import enforce_caption_limit, process_event_generation
from bot.event_generator.command import event_generate_command
from core.ai_parser import GeminiQuotaError


class TestEventGenerator(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = self.test_db_path
        db.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()
        config.DB_PATH = self.orig_db_path

    def test_fetch_bgg_game_image_exact_match(self):
        with patch("requests.get") as mock_get:
            # 1. Search response
            search_resp = MagicMock()
            search_resp.status_code = 200
            search_resp.json.return_value = {
                "items": [
                    {"objectid": 999, "name": "54x80mm Catan Sleeves"},
                    {"objectid": 13, "name": "Catan"},
                ]
            }
            # 2. Detail response
            detail_resp = MagicMock()
            detail_resp.status_code = 200
            detail_resp.json.return_value = {
                "item": {
                    "imageurl": "https://example.com/catan_thumb.jpg",
                    "images": {"original": "https://example.com/catan_orig.jpg"},
                }
            }
            # 3. Image download response
            img_resp = MagicMock()
            img_resp.status_code = 200
            img_resp.content = b"CATAN_IMAGE_BYTES"

            mock_get.side_effect = [search_resp, detail_resp, img_resp]

            result = fetch_bgg_game_image("Catan")
            self.assertEqual(result, b"CATAN_IMAGE_BYTES")
            self.assertEqual(mock_get.call_count, 3)
            # Check detail URL used objectid 13 (exact match)
            self.assertIn("objectid=13", mock_get.call_args_list[1][0][0])
            self.assertEqual(mock_get.call_args_list[2][0][0], "https://example.com/catan_orig.jpg")

    def test_fetch_bgg_game_image_filters_accessory(self):
        with patch("requests.get") as mock_get:
            search_resp = MagicMock()
            search_resp.status_code = 200
            search_resp.json.return_value = {
                "items": [
                    {"objectid": 111, "name": "Root Playmat Neoprene"},
                    {"objectid": 222, "name": "Root: A Game of Woodland Might and Right"},
                ]
            }
            detail_resp = MagicMock()
            detail_resp.status_code = 200
            detail_resp.json.return_value = {
                "item": {"imageurl": "//example.com/root.jpg"}
            }
            img_resp = MagicMock()
            img_resp.status_code = 200
            img_resp.content = b"ROOT_IMAGE"

            mock_get.side_effect = [search_resp, detail_resp, img_resp]

            result = fetch_bgg_game_image("Root")
            self.assertEqual(result, b"ROOT_IMAGE")
            # Chosen objectid should be 222 because 111 is an accessory
            self.assertIn("objectid=222", mock_get.call_args_list[1][0][0])
            # Check leading // was prefixed with https:
            self.assertEqual(mock_get.call_args_list[2][0][0], "https://example.com/root.jpg")

    def test_fetch_bgg_game_image_empty_or_error(self):
        self.assertIsNone(fetch_bgg_game_image(""))
        with patch("requests.get") as mock_get:
            mock_get.return_value.status_code = 404
            self.assertIsNone(fetch_bgg_game_image("NonexistentGame"))

    def test_generate_event_data_with_ai_success(self):
        fake_ai_json = {
            "title": "Catan & Wingspan",
            "games": ["Catan", "Wingspan"],
            "date": "Sabato 10-10-2026 21:00",
            "normalized_date": "10-10-2026",
            "system": "Board Game",
            "host": "@Destard",
            "seats": "4/4",
            "max_seats": 4,
            "extra_info": "Adatto a neofiti",
            "is_roleplay": False,
            "description": "Una fantastica serata all'insegna dei giochi da tavolo!",
        }
        with patch("google.generativeai.GenerativeModel") as mock_model_cls:
            mock_model = MagicMock()
            mock_resp = MagicMock()
            mock_resp.text = f"```json\n{json.dumps(fake_ai_json)}\n```"
            mock_model.generate_content.return_value = mock_resp
            mock_model_cls.return_value = mock_model

            data = generate_event_data_with_ai("Catan e Wingspan sabato 10 ottobre ore 21 host Destard")
            self.assertIsNotNone(data)
            self.assertEqual(data["title"], "Catan & Wingspan")
            self.assertEqual(data["games"], ["Catan", "Wingspan"])
            self.assertEqual(data["booked_seats"], 0)
            self.assertEqual(data["max_seats"], 4)
            self.assertFalse(data["is_roleplay"])

    def test_generate_event_data_with_ai_quota_error(self):
        with patch("google.generativeai.GenerativeModel") as mock_model_cls:
            mock_model = MagicMock()
            mock_model.generate_content.side_effect = Exception("429 Your prepayment credits are depleted")
            mock_model_cls.return_value = mock_model

            with self.assertRaises(GeminiQuotaError):
                generate_event_data_with_ai("prompt")


    def test_enforce_caption_limit_under_1024(self):
        ev = {
            "title": "Catan",
            "date": "10-10-2026",
            "system": "Board Game",
            "host": "Host",
            "seats": "4/4",
            "description": "Breve descrizione.",
        }
        res = enforce_caption_limit(ev, max_length=1024)
        self.assertLessEqual(len(res), 1024)
        self.assertEqual(ev["description"], "Breve descrizione.")

    def test_enforce_caption_limit_over_1024_trims_description(self):
        long_desc = "Questa è una descrizione lunghissima! " * 40
        ev = {
            "title": "Catan",
            "date": "10-10-2026",
            "system": "Board Game",
            "host": "Host",
            "seats": "4/4",
            "description": long_desc,
        }
        res = enforce_caption_limit(ev, max_length=1024)
        self.assertLessEqual(len(res), 1024)
        self.assertTrue(ev["description"].endswith("..."))
        self.assertLess(len(ev["description"]), len(long_desc))

    async def test_process_event_generation_single_game_no_collage(self):
        ev_data = {
            "title": "Catan",
            "games": ["Catan"],
            "date": "10-10-2026",
            "normalized_date": "10-10-2026",
            "system": "Board Game",
            "host": "Host",
            "seats": "4/4",
            "description": "Descrizione",
        }
        context = MagicMock()
        context.bot.send_photo = AsyncMock()
        fake_photo_msg = MagicMock()
        fake_photo_msg.message_id = 12345
        context.bot.send_photo.return_value = fake_photo_msg

        with patch("bot.event_generator.pipeline.generate_event_data_with_ai", return_value=ev_data), \
             patch("bot.event_generator.pipeline.fetch_bgg_game_image", return_value=b"SINGLE_IMG_BYTES"), \
             patch("bot.event_generator.pipeline.create_collage_from_bytes") as mock_collage, \
             patch("bot.event_generator.pipeline.save_image_locally", return_value=self.temp_dir.name + "/test.jpg"), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()):

            success, msg = await process_event_generation("Catan, 10 ottobre", context)
            self.assertTrue(success)
            mock_collage.assert_not_called()
            context.bot.send_photo.assert_called_once()

    async def test_process_event_generation_multiple_games_collaged(self):
        ev_data = {
            "title": "Catan & Wingspan",
            "games": ["Catan", "Wingspan"],
            "date": "10-10-2026",
            "normalized_date": "10-10-2026",
            "system": "Board Game",
            "host": "Host",
            "seats": "4/4",
            "description": "Descrizione",
        }
        context = MagicMock()
        context.bot.send_photo = AsyncMock()
        fake_photo_msg = MagicMock()
        fake_photo_msg.message_id = 54321
        context.bot.send_photo.return_value = fake_photo_msg

        with patch("bot.event_generator.pipeline.generate_event_data_with_ai", return_value=ev_data), \
             patch("bot.event_generator.pipeline.fetch_bgg_game_image", side_effect=[b"IMG_1", b"IMG_2"]), \
             patch("bot.event_generator.pipeline.create_collage_from_bytes", return_value=b"COLLAGE_BYTES") as mock_collage, \
             patch("bot.event_generator.pipeline.save_image_locally", return_value=self.temp_dir.name + "/collage.jpg"), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()):

            success, msg = await process_event_generation("Catan e Wingspan", context)
            self.assertTrue(success)
            mock_collage.assert_called_once()
            self.assertEqual(mock_collage.call_args[0][0], [b"IMG_1", b"IMG_2"])



    async def test_process_event_generation_multiple_games_single_image_no_collage(self):
        ev_data = {
            "title": "Catan & UnfindableGame",
            "games": ["Catan", "UnfindableGame"],
            "date": "10-10-2026",
            "normalized_date": "10-10-2026",
            "system": "Board Game",
            "host": "Host",
            "seats": "4/4",
            "description": "Descrizione",
        }
        context = MagicMock()
        context.bot.send_photo = AsyncMock()
        fake_photo_msg = MagicMock()
        fake_photo_msg.message_id = 99999
        context.bot.send_photo.return_value = fake_photo_msg

        with patch("bot.event_generator.pipeline.generate_event_data_with_ai", return_value=ev_data), \
             patch("bot.event_generator.pipeline.fetch_bgg_game_image", side_effect=[b"IMG_1", None]), \
             patch("bot.event_generator.pipeline.create_collage_from_bytes") as mock_collage, \
             patch("bot.event_generator.pipeline.save_image_locally", return_value=self.temp_dir.name + "/single.jpg"), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()):

            success, msg = await process_event_generation("prompt", context)
            self.assertTrue(success)
            mock_collage.assert_not_called()

    async def test_event_generate_command_unauthorized(self):
        update = MagicMock()
        update.effective_chat.id = 99999
        update.message.reply_text = AsyncMock()
        update.effective_message = update.message
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "12345"):
            await event_generate_command(update, context)
            update.message.reply_text.assert_called_once_with("Non sei autorizzato.")

    async def test_event_generate_command_no_text_shows_help(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.text = "/event_generate"
        update.message.caption = None
        update.message.reply_to_message = None
        update.message.reply_text = AsyncMock()
        update.effective_message = update.message
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "12345"):
            await event_generate_command(update, context)
            update.message.reply_text.assert_called_once()
            self.assertIn("Uso del comando /event_generate", update.message.reply_text.call_args[0][0])

    async def test_event_generate_command_success(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.text = "/event_generate Catan, venerdì 10 ottobre, host Destard"
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=status_msg)
        update.effective_message = update.message
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "12345"), \
             patch("bot.event_generator.command.process_event_generation", AsyncMock(return_value=(True, "Successo"))):
            await event_generate_command(update, context)
            status_msg.edit_text.assert_called_once_with("✅ Successo")

    async def test_event_generate_command_none_message_handled_gracefully(self):
        update = MagicMock()
        update.message = None
        update.effective_message = None
        update.channel_post = None
        context = MagicMock()

        # Should return cleanly without raising AttributeError: 'NoneType' object has no attribute 'text'
        await event_generate_command(update, context)

    async def test_event_generate_command_channel_post_fallback(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message = None
        channel_post = MagicMock()
        channel_post.text = "/event_generate Root, domani 21:00, host Marco"
        channel_post.caption = None
        channel_post.reply_to_message = None
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        channel_post.reply_text = AsyncMock(return_value=status_msg)
        update.effective_message = channel_post
        update.channel_post = channel_post
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "12345"), \
             patch("bot.event_generator.command.process_event_generation", AsyncMock(return_value=(True, "Successo"))):
            await event_generate_command(update, context)
            status_msg.edit_text.assert_called_once_with("✅ Successo")


