import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import core.db as db
from core import config
from core.ai_parser import GeminiQuotaError


class TestDeferredMessageDeletion(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = self.test_db_path
        db.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()
        config.DB_PATH = self.orig_db_path

    async def test_single_message_non_event_preserved_in_channel(self):
        from bot.handlers.ingestion import process_message
        from bot.handlers.albums import media_groups

        media_groups.clear()
        public_channel_id = "-100123456789"
        admin_chat_id = "999"

        message = MagicMock()
        message.chat_id = public_channel_id
        message.media_group_id = None
        message.from_user.is_bot = False
        message.reply_markup = None
        message.text = "Descrizione: Avviso ai soci, sabato la sede sarà chiusa per manutenzione."
        message.caption = None
        message.photo = None
        message.message_id = 501
        message.delete = AsyncMock()

        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.send_photo = AsyncMock()
        update = MagicMock(message=message, channel_post=None)

        non_event_data = {
            "is_event": False,
            "reason": "General announcement about venue closure"
        }

        with patch("core.config.PUBLIC_CHANNEL_ID", public_channel_id), \
             patch("core.config.ADMIN_CHAT_ID", admin_chat_id), \
             patch("bot.handlers.extraction.parse_event_message", return_value=non_event_data) as mock_parser:

            await process_message(update, context)

            mock_parser.assert_called_once_with(message.text)
            # Original message in public channel was NOT deleted
            message.delete.assert_not_called()
            # No admin notification was sent
            context.bot.send_message.assert_not_called()
            # No event was stored in database
            with db.get_connection() as conn:
                events = conn.cursor().execute("SELECT * FROM events").fetchall()
            self.assertEqual(len(events), 0)

    async def test_single_message_confirmed_event_deleted_from_channel(self):
        from bot.handlers.ingestion import process_message
        from bot.handlers.albums import media_groups

        media_groups.clear()
        public_channel_id = "-100123456789"
        admin_chat_id = "999"

        message = MagicMock()
        message.chat_id = public_channel_id
        message.media_group_id = None
        message.from_user.is_bot = False
        message.reply_markup = None
        message.text = "Titolo: D&D 5e: Phandelver\nQuando: Sabato 12-09-2026 ore 21:00\nMaster: Gandalf\nPosti liberi: 5"
        message.caption = None
        message.photo = None
        message.message_id = 502
        message.delete = AsyncMock()

        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.send_photo = AsyncMock()
        update = MagicMock(message=message, channel_post=None)

        event_data = {
            "is_event": True,
            "title": "D&D 5e: Phandelver",
            "date": "Sabato 12-09-2026 ore 21:00",
            "normalized_date": "2026-09-12",
            "time": "21:00",
            "master": "Gandalf",
            "system": "D&D 5e",
            "available_seats": 5,
            "total_seats": 5,
            "description": "Avventura livello 1"
        }

        with patch("core.config.PUBLIC_CHANNEL_ID", public_channel_id), \
             patch("core.config.ADMIN_CHAT_ID", admin_chat_id), \
             patch("bot.handlers.extraction.parse_event_message", return_value=event_data) as mock_parser:

            await process_message(update, context)

            mock_parser.assert_called_once_with(message.text)
            # Confirmed event MUST be deleted from the public channel
            message.delete.assert_called_once()
    async def test_media_group_non_event_all_messages_preserved(self):
        from bot.handlers.ingestion import process_message
        from bot.handlers.albums import media_groups

        media_groups.clear()
        media_group_id = "album_notice_1"
        public_channel_id = "-100123456789"
        admin_chat_id = "999"

        m1 = MagicMock()
        m1.chat_id = public_channel_id
        m1.media_group_id = media_group_id
        m1.from_user.is_bot = False
        m1.reply_markup = None
        m1.text = None
        m1.caption = "Descrizione: Nuove miniature per gioco da tavolo arrivate in associazione! Venite a vederle!"
        m1.message_id = 601
        m1.delete = AsyncMock()
        p1 = MagicMock()
        p1.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b"dummy1"))))
        m1.photo = [p1]

        m2 = MagicMock()
        m2.chat_id = public_channel_id
        m2.media_group_id = media_group_id
        m2.from_user.is_bot = False
        m2.reply_markup = None
        m2.text = None
        m2.caption = None
        m2.message_id = 602
        m2.delete = AsyncMock()
        p2 = MagicMock()
        p2.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b"dummy2"))))
        m2.photo = [p2]

        context = MagicMock()
        context.bot.send_message = AsyncMock()
        update1 = MagicMock(message=m1, channel_post=None)
        update2 = MagicMock(message=m2, channel_post=None)

        non_event_data = {
            "is_event": False,
            "reason": "Showcase of miniatures, not a bookable game session"
        }

        async def fast_sleep(secs):
            if media_group_id in media_groups:
                media_groups[media_group_id]["last_received"] = 0
            return

        with patch("core.config.PUBLIC_CHANNEL_ID", public_channel_id), \
             patch("core.config.ADMIN_CHAT_ID", admin_chat_id), \
             patch("bot.handlers.albums.asyncio.sleep", side_effect=fast_sleep), \
             patch("bot.handlers.albums.create_collage_from_bytes", return_value=b"collage"), \
             patch("bot.handlers.extraction.parse_event_message", return_value=non_event_data) as mock_parser:

            await process_message(update1, context)
            await process_message(update2, context)

            if media_group_id in media_groups and media_groups[media_group_id]["task"]:
                await media_groups[media_group_id]["task"]

            mock_parser.assert_called_once()
            # Neither photo message in the album should be deleted
            m1.delete.assert_not_called()
            m2.delete.assert_not_called()

            # No event stored in DB
            with db.get_connection() as conn:
                events = conn.cursor().execute("SELECT * FROM events").fetchall()
            self.assertEqual(len(events), 0)

    async def test_media_group_confirmed_event_all_messages_deleted(self):
        from bot.handlers.ingestion import process_message
        from bot.handlers.albums import media_groups

        media_groups.clear()
        media_group_id = "album_event_1"
        public_channel_id = "-100123456789"
        admin_chat_id = "999"

        m1 = MagicMock()
        m1.chat_id = public_channel_id
        m1.media_group_id = media_group_id
        m1.from_user.is_bot = False
        m1.reply_markup = None
        m1.text = None
        m1.caption = "Titolo: Campagna Call of Cthulhu\nQuando: Sabato 19-09-2026 ore 21:00\nPosti liberi: 4"
        m1.message_id = 701
        m1.delete = AsyncMock()
        p1 = MagicMock()
        p1.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b"dummy1"))))
        m1.photo = [p1]

        m2 = MagicMock()
        m2.chat_id = public_channel_id
        m2.media_group_id = media_group_id
        m2.from_user.is_bot = False
        m2.reply_markup = None
        m2.text = None
        m2.caption = None
        m2.message_id = 702
        m2.delete = AsyncMock()
        p2 = MagicMock()
        p2.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b"dummy2"))))
        m2.photo = [p2]

        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.send_photo = AsyncMock()
        update1 = MagicMock(message=m1, channel_post=None)
        update2 = MagicMock(message=m2, channel_post=None)

        event_data = {
            "is_event": True,
            "title": "Call of Cthulhu",
            "date": "Sabato 19-09-2026 ore 21:00",
            "normalized_date": "2026-09-19",
            "time": "21:00",
            "master": "Lovecraft",
            "system": "Call of Cthulhu 7e",
            "available_seats": 4,
            "total_seats": 4,
            "description": "Orrore cosmico"
        }

        async def fast_sleep(secs):
            if media_group_id in media_groups:
                media_groups[media_group_id]["last_received"] = 0
            return

        with patch("core.config.PUBLIC_CHANNEL_ID", public_channel_id), \
             patch("core.config.ADMIN_CHAT_ID", admin_chat_id), \
             patch("bot.handlers.albums.asyncio.sleep", side_effect=fast_sleep), \
             patch("bot.handlers.albums.create_collage_from_bytes", return_value=b"collage"), \
             patch("bot.handlers.extraction.parse_event_message", return_value=event_data) as mock_parser:

            await process_message(update1, context)
            await process_message(update2, context)

            if media_group_id in media_groups and media_groups[media_group_id]["task"]:
                await media_groups[media_group_id]["task"]

            mock_parser.assert_called_once()
            # Both photo messages in the album MUST be deleted
            m1.delete.assert_called_once()
            m2.delete.assert_called_once()

            # Event stored in DB
            with db.get_connection() as conn:
                events = conn.cursor().execute("SELECT * FROM events").fetchall()
            self.assertEqual(len(events), 1)

    async def test_quota_error_preserves_channel_message(self):
        from bot.handlers.ingestion import process_message
        from bot.handlers.albums import media_groups

        media_groups.clear()
        public_channel_id = "-100123456789"
        admin_chat_id = "999"

        message = MagicMock()
        message.chat_id = public_channel_id
        message.media_group_id = None
        message.from_user.is_bot = False
        message.reply_markup = None
        message.text = "Sessione One-shot Cyberpunk Red Sabato 19-09-2026"
        message.caption = None
        message.photo = None
        message.message_id = 801
        message.delete = AsyncMock()

        context = MagicMock()
        context.bot.send_message = AsyncMock()
        update = MagicMock(message=message, channel_post=None)

        err_text = "429 Your prepayment credits are depleted."
        with patch("core.config.PUBLIC_CHANNEL_ID", public_channel_id), \
             patch("core.config.ADMIN_CHAT_ID", admin_chat_id), \
             patch("bot.handlers.extraction.parse_event_message", side_effect=GeminiQuotaError(err_text)):

            await process_message(update, context)

            # Channel message preserved because extraction failed
            message.delete.assert_not_called()
            # Admin alerted about quota depletion
            context.bot.send_message.assert_called_once()
            self.assertIn("429", context.bot.send_message.call_args.kwargs.get("text", ""))


            # No event stored in DB
            with db.get_connection() as conn:
                events = conn.cursor().execute("SELECT * FROM events").fetchall()
            self.assertEqual(len(events), 0)
