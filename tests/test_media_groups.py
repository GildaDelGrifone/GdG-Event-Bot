import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import core.db as db
from core import config


class TestMultiImageCollageAndMediaGroup(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = self.test_db_path
        db.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()
        config.DB_PATH = self.orig_db_path

    def _create_dummy_image_bytes(self, width, height, color):
        import io
        from PIL import Image
        img = Image.new("RGB", (width, height), color=color)
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()

    def test_build_horizontal_collage_proportions_and_dimensions(self):
        import io
        from PIL import Image
        from utils.image_utils import build_horizontal_collage, create_collage_from_bytes

        # Create 3 dummy images of different heights and widths
        b1 = self._create_dummy_image_bytes(200, 300, (255, 0, 0))   # aspect ratio 2/3
        b2 = self._create_dummy_image_bytes(400, 500, (0, 255, 0))   # aspect ratio 4/5
        b3 = self._create_dummy_image_bytes(300, 400, (0, 0, 255))   # aspect ratio 3/4

        collage_bytes = create_collage_from_bytes([b1, b2, b3])
        self.assertIsNotNone(collage_bytes)

        collage_img = Image.open(io.BytesIO(collage_bytes))
        avg_height = int((300 + 500 + 400) / 3) # 400
        self.assertEqual(collage_img.height, avg_height)

        expected_w1 = int(200 * (400 / 300))
        expected_w2 = int(400 * (400 / 500))
        expected_w3 = int(300 * (400 / 400))
        expected_total_width = expected_w1 + expected_w2 + expected_w3
        self.assertEqual(collage_img.width, expected_total_width)

    def test_build_collage_multi_row_wrap(self):
        import io
        from PIL import Image
        from utils.image_utils import build_horizontal_collage

        # Create 5 dummy images (all 100x100)
        images = [Image.new('RGB', (100, 100), color=(i * 20, i * 20, i * 20)) for i in range(5)]

        # Wrap at 2 per row -> 3 rows (2, 2, 1)
        collage = build_horizontal_collage(images, max_per_row=2)
        self.assertIsNotNone(collage)
        self.assertEqual(collage.height, 300) # 3 rows of height 100
        self.assertEqual(collage.width, 200) # max row width is 2 * 100 = 200

        # Wrap at 3 per row -> 2 rows (3, 2)
        collage = build_horizontal_collage(images, max_per_row=3)
        self.assertIsNotNone(collage)
        self.assertEqual(collage.height, 200) # 2 rows of height 100
        self.assertEqual(collage.width, 300) # max row width is 3 * 100 = 300

    def test_create_collage_from_bytes_single_and_empty(self):
        from utils.image_utils import create_collage_from_bytes

        self.assertIsNone(create_collage_from_bytes([]))
        self.assertIsNone(create_collage_from_bytes(None))

        b1 = self._create_dummy_image_bytes(100, 100, (10, 20, 30))
        single_result = create_collage_from_bytes([b1])
        self.assertEqual(single_result, b1)
    async def test_media_group_event_buffering_and_collage_creation(self):
        import io
        from PIL import Image
        from bot.handlers.ingestion import process_message
        from bot.handlers.albums import media_groups

        media_groups.clear()

        b1 = self._create_dummy_image_bytes(200, 400, (255, 0, 0))
        b2 = self._create_dummy_image_bytes(300, 400, (0, 255, 0))
        b3 = self._create_dummy_image_bytes(400, 400, (0, 0, 255))

        media_group_id = "album_12345"
        public_channel_id = "-100123456789"
        admin_chat_id = "999"

        # Message 1: photo 1, no caption
        m1 = MagicMock()
        m1.chat_id = public_channel_id
        m1.media_group_id = media_group_id
        m1.from_user.is_bot = False
        m1.reply_markup = None
        m1.text = None
        m1.caption = None
        m1.message_id = 101
        m1.delete = AsyncMock()
        p1 = MagicMock()
        p1.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b1))))
        m1.photo = [p1]

        # Message 2: photo 2, contains the caption
        m2 = MagicMock()
        m2.chat_id = public_channel_id
        m2.media_group_id = media_group_id
        m2.from_user.is_bot = False
        m2.reply_markup = None
        m2.text = None
        m2.caption = "Titolo: Sessione Speciale D&D\nQuando: Sabato 05-09-2026 ore 21:00\nPosti liberi: 4/5\nMaster: Gandalf"
        m2.message_id = 102
        m2.delete = AsyncMock()
        p2 = MagicMock()
        p2.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b2))))
        m2.photo = [p2]

        # Message 3: photo 3, no caption
        m3 = MagicMock()
        m3.chat_id = public_channel_id
        m3.media_group_id = media_group_id
        m3.from_user.is_bot = False
        m3.reply_markup = None
        m3.text = None
        m3.caption = None
        m3.message_id = 103
        m3.delete = AsyncMock()
        p3 = MagicMock()
        p3.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b3))))
        m3.photo = [p3]

        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.send_photo = AsyncMock()

        update1 = MagicMock(message=m1, channel_post=None)
        update2 = MagicMock(message=m2, channel_post=None)
        update3 = MagicMock(message=m3, channel_post=None)

        async def fast_sleep(secs):
            if media_group_id in media_groups:
                media_groups[media_group_id]["last_received"] = 0
            return

        with patch("core.config.PUBLIC_CHANNEL_ID", public_channel_id), \
             patch("core.config.ADMIN_CHAT_ID", admin_chat_id), \
             patch("core.config.DATA_DIR", self.temp_dir.name), \
             patch("bot.handlers.albums.asyncio.sleep", side_effect=fast_sleep), \
             patch("bot.handlers.extraction.parse_event_message", return_value={
                 "is_event": True,
                 "title": "Sessione Speciale D&D",
                 "date": "Sabato 05-09-2026 21:00",
                 "normalized_date": "05-09-2026",
                 "seats": "4/4",
                 "max_seats": 4,
                 "booked_seats": 0,
             }):

            await process_message(update1, context)
            await process_message(update2, context)
            await process_message(update3, context)

            if media_group_id in media_groups and media_groups[media_group_id]["task"]:
                await media_groups[media_group_id]["task"]

        # 1. Verify all 3 messages were deleted from public channel
        m1.delete.assert_called_once()
        m2.delete.assert_called_once()
        m3.delete.assert_called_once()

        # 2. Verify media group entry was cleared from memory
        self.assertNotIn(media_group_id, media_groups)

        # 3. Verify event was inserted into DB
        with db.get_connection() as conn:
            import sqlite3
            conn.row_factory = sqlite3.Row
            events = conn.cursor().execute("SELECT * FROM events").fetchall()
        self.assertEqual(len(events), 1)
        event = events[0]

        # 4. Verify image_path points to saved collage with 'event_' prefix
        self.assertIsNotNone(event["image_path"])
        self.assertTrue(os.path.basename(event["image_path"]).startswith("event_"))
        self.assertTrue(os.path.exists(event["image_path"]))

        # 5. Check the saved image dimensions (horizontal collage)
        with Image.open(event["image_path"]) as saved_img:
            self.assertEqual(saved_img.height, 400)
            self.assertEqual(saved_img.width, 200 + 300 + 400) # 900

    async def test_media_group_without_caption_ignored(self):
        from bot.handlers.ingestion import process_message
        from bot.handlers.albums import media_groups

        media_groups.clear()
        b1 = self._create_dummy_image_bytes(100, 100, (255, 0, 0))
        media_group_id = "album_nocaption"
        public_channel_id = "-100123456789"

        m1 = MagicMock()
        m1.chat_id = public_channel_id
        m1.media_group_id = media_group_id
        m1.from_user.is_bot = False
        m1.reply_markup = None
        m1.text = None
        m1.caption = None
        m1.message_id = 201
        m1.delete = AsyncMock()
        p1 = MagicMock()
        p1.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b1))))
        m1.photo = [p1]

        context = MagicMock()
        update1 = MagicMock(message=m1, channel_post=None)

        async def fast_sleep(secs):
            if media_group_id in media_groups:
                media_groups[media_group_id]["last_received"] = 0
            return

        with patch("core.config.PUBLIC_CHANNEL_ID", public_channel_id), \
             patch("bot.handlers.albums.asyncio.sleep", side_effect=fast_sleep), \
             patch("bot.handlers.albums.handle_event_extraction") as mock_extract:

            await process_message(update1, context)
            if media_group_id in media_groups and media_groups[media_group_id]["task"]:
                await media_groups[media_group_id]["task"]

            # Messages without caption are not events and must NOT be deleted from the public channel
            m1.delete.assert_not_called()
            mock_extract.assert_not_called()

    async def test_single_photo_message_processed_immediately(self):
        from bot.handlers.ingestion import process_message
        from bot.handlers.albums import media_groups

        media_groups.clear()
        b1 = self._create_dummy_image_bytes(100, 100, (255, 0, 0))
        public_channel_id = "-100123456789"

        m1 = MagicMock()
        m1.chat_id = public_channel_id
        m1.media_group_id = None # single message
        m1.from_user.is_bot = False
        m1.reply_markup = None
        m1.text = None
        m1.caption = "Sessione Singola D&D Sabato 05-09-2026 ore 21:00 Posti 4/5"
        m1.message_id = 301
        m1.delete = AsyncMock()
        p1 = MagicMock()
        p1.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b1))))
        m1.photo = [p1]

        context = MagicMock()
        update1 = MagicMock(message=m1, channel_post=None)

        async def fake_handle_extraction(*args, **kwargs):
            del_cb = kwargs.get("delete_callback")
            if del_cb:
                await del_cb()
            return True

        with patch("core.config.PUBLIC_CHANNEL_ID", public_channel_id), \
             patch("bot.handlers.ingestion.handle_event_extraction", side_effect=fake_handle_extraction) as mock_extract:

            await process_message(update1, context)

            m1.delete.assert_called_once()
            self.assertEqual(len(media_groups), 0)
            mock_extract.assert_called_once()
            extracted_text = mock_extract.call_args.kwargs.get("text") if mock_extract.call_args.kwargs else mock_extract.call_args[0][0]
            extracted_bytes = mock_extract.call_args.kwargs.get("image_bytes") if mock_extract.call_args.kwargs else mock_extract.call_args[0][1]
            self.assertEqual(extracted_text, m1.caption)
            self.assertEqual(extracted_bytes, bytearray(b1))







class TestAdminMediaGroupManualProcessing(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from bot.handlers.albums import admin_media_groups
        admin_media_groups.clear()

    def tearDown(self):
        from bot.handlers.albums import admin_media_groups
        admin_media_groups.clear()

    async def test_cache_admin_media_group_and_cleanup(self):
        from bot.handlers.albums import cache_admin_media_group, admin_media_groups, cleanup_admin_media_cache

        # Prepare 2 messages belonging to the same media group
        update1 = MagicMock()
        update1.message = MagicMock()
        update1.message.media_group_id = "mg_album_1"
        update1.message.message_id = 100
        update1.message.caption = "Didascalia dell'album"
        photo1 = MagicMock()
        photo_file1 = MagicMock()
        photo_file1.download_as_bytearray = AsyncMock(return_value=bytearray(b"image_1_data"))
        photo1.get_file = AsyncMock(return_value=photo_file1)
        update1.message.photo = [photo1]

        update2 = MagicMock()
        update2.message = MagicMock()
        update2.message.media_group_id = "mg_album_1"
        update2.message.message_id = 101
        update2.message.caption = None
        photo2 = MagicMock()
        photo_file2 = MagicMock()
        photo_file2.download_as_bytearray = AsyncMock(return_value=bytearray(b"image_2_data"))
        photo2.get_file = AsyncMock(return_value=photo_file2)
        update2.message.photo = [photo2]

        context = MagicMock()

        await cache_admin_media_group(update1, context)
        await cache_admin_media_group(update2, context)

        self.assertIn("mg_album_1", admin_media_groups)
        entry = admin_media_groups["mg_album_1"]
        self.assertEqual(len(entry["images"]), 2)
        self.assertEqual(entry["images"][100], bytearray(b"image_1_data"))
        self.assertEqual(entry["images"][101], bytearray(b"image_2_data"))
        self.assertEqual(entry["captions"][100], "Didascalia dell'album")

        # Test cleanup with max_age_seconds
        cleanup_admin_media_cache(now=entry["last_received"] + 4000, max_age_seconds=3600)
        self.assertNotIn("mg_album_1", admin_media_groups)

    async def test_manual_trigger_with_cached_media_group_creates_collage(self):
        from bot.handlers.ingestion import manual_trigger_command
        from bot.handlers.albums import admin_media_groups

        # Seed cached media group with 2 photos
        admin_media_groups["album_test"] = {
            "images": {
                200: bytearray(b"img_bytes_1"),
                201: bytearray(b"img_bytes_2")
            },
            "captions": {
                200: "Titolo: Gioco di Ruolo\nData: 10-10-2026 21:00\nSistema: D&D"
            },
            "last_received": 0.0,
            "pending_downloads": 0
        }

        # User replies /ep to the SECOND photo (message_id 201, which has NO caption)
        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = "/ep"
        update.message.caption = None
        update.message.reply_text = AsyncMock()

        target_msg = MagicMock()
        target_msg.media_group_id = "album_test"
        target_msg.message_id = 201
        target_msg.text = None
        target_msg.caption = None
        target_msg.photo = [MagicMock()]
        target_msg.link = "https://t.me/c/999/201"
        update.message.reply_to_message = target_msg

        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.albums.create_collage_from_bytes", return_value=b"stitched_collage_bytes") as mock_collage, \
             patch("bot.handlers.ingestion.handle_event_extraction", new_callable=AsyncMock) as mock_extract:

            mock_extract.return_value = True

            await manual_trigger_command(update, context)

            mock_collage.assert_called_once_with([bytearray(b"img_bytes_1"), bytearray(b"img_bytes_2")])
            mock_extract.assert_called_once_with(
                "Titolo: Gioco di Ruolo\nData: 10-10-2026 21:00\nSistema: D&D",
                b"stitched_collage_bytes",
                context,
                "https://t.me/c/999/201",
                201,
                is_manual_trigger=True
            )
            update.message.reply_text.assert_called_once_with("Processato il messaggio risposto.")

    async def test_manual_trigger_custom_text_overrides_album_caption(self):
        from bot.handlers.ingestion import manual_trigger_command
        from bot.handlers.albums import admin_media_groups

        admin_media_groups["album_test2"] = {
            "images": {
                300: bytearray(b"img_bytes_A"),
                301: bytearray(b"img_bytes_B")
            },
            "captions": {
                300: "Didascalia originale"
            },
            "last_received": 0.0,
            "pending_downloads": 0
        }

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = "/ep Testo personalizzato dell'evento"
        update.message.caption = None
        update.message.reply_text = AsyncMock()

        target_msg = MagicMock()
        target_msg.media_group_id = "album_test2"
        target_msg.message_id = 300
        target_msg.text = None
        target_msg.caption = "Didascalia originale"
        target_msg.photo = [MagicMock()]
        target_msg.link = "https://t.me/c/999/300"
        update.message.reply_to_message = target_msg

        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.albums.create_collage_from_bytes", return_value=b"collage_custom"), \
             patch("bot.handlers.ingestion.handle_event_extraction", new_callable=AsyncMock) as mock_extract:

            mock_extract.return_value = True

            await manual_trigger_command(update, context)

            mock_extract.assert_called_once_with(
                "Testo personalizzato dell'evento",
                b"collage_custom",
                context,
                "https://t.me/c/999/300",
                300,
                is_manual_trigger=True
            )

    async def test_manual_trigger_fallback_when_not_in_cache(self):
        from bot.handlers.ingestion import manual_trigger_command

        # Target message has media_group_id, but it is NOT in cache
        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = "/ep"
        update.message.caption = None
        update.message.reply_text = AsyncMock()

        photo_single = MagicMock()
        photo_file = MagicMock()
        photo_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"single_photo_fallback"))
        photo_single.get_file = AsyncMock(return_value=photo_file)

        target_msg = MagicMock()
        target_msg.media_group_id = "non_cached_album"
        target_msg.message_id = 400
        target_msg.text = None
        target_msg.caption = "Testo evento fallback"
        target_msg.photo = [photo_single]
        target_msg.link = "https://t.me/c/999/400"
        update.message.reply_to_message = target_msg

        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.ingestion.handle_event_extraction", new_callable=AsyncMock) as mock_extract:

            mock_extract.return_value = True

            await manual_trigger_command(update, context)

            mock_extract.assert_called_once_with(
                "Testo evento fallback",
                bytearray(b"single_photo_fallback"),
                context,
                "https://t.me/c/999/400",
                400,
                is_manual_trigger=True
            )
            update.message.reply_text.assert_called_once_with("Processato il messaggio risposto.")

    async def test_manual_trigger_no_text_informs_user(self):
        from bot.handlers.ingestion import manual_trigger_command

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = "/ep"
        update.message.caption = None
        update.message.reply_text = AsyncMock()

        target_msg = MagicMock()
        target_msg.media_group_id = None
        target_msg.message_id = 500
        target_msg.text = None
        target_msg.caption = None
        target_msg.photo = [MagicMock()]
        target_msg.photo[-1].get_file = AsyncMock()
        target_msg.photo[-1].get_file.return_value.download_as_bytearray = AsyncMock(return_value=bytearray(b"photo"))
        update.message.reply_to_message = target_msg

        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.ingestion.handle_event_extraction", new_callable=AsyncMock) as mock_extract:

            await manual_trigger_command(update, context)

            mock_extract.assert_not_called()
            update.message.reply_text.assert_called_once_with(
                "Nessun testo trovato nel messaggio o nel comando. Includi il testo o invia una didascalia."
            )



if __name__ == "__main__":
    unittest.main()
