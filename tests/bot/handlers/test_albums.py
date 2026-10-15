import os
import sqlite3
import unittest
from unittest.mock import patch

from PIL import Image

import core.db as db
from bot.handlers.albums import (
    admin_media_groups,
    cache_admin_media_group,
    cleanup_admin_media_cache,
    extract_image_bytes_from_update,
    media_groups,
)
from bot.handlers.ingestion import process_message
from tests.support.config import as_admin_chat, patched_config
from tests.support.db import TempDBMixin
from tests.support.images import image_bytes
from tests.support.telegram import channel_message, make_context, make_message, make_update, telegram_photo

PUBLIC_CHANNEL_ID = "-100123456789"


def album_photo(media_group_id, message_id, data, caption=None):
    return channel_message(PUBLIC_CHANNEL_ID, message_id, caption=caption, media_group_id=media_group_id,
                           photo=[telegram_photo(data)])


def skip_debounce(media_group_id):
    """asyncio.sleep replacement that makes the album look complete immediately."""
    async def fast_sleep(_secs):
        if media_group_id in media_groups:
            media_groups[media_group_id]["last_received"] = 0
    return fast_sleep


async def wait_for_album(media_group_id):
    if media_group_id in media_groups and media_groups[media_group_id]["task"]:
        await media_groups[media_group_id]["task"]


class TestChannelAlbums(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        media_groups.clear()
        self.addCleanup(media_groups.clear)

    async def test_media_group_event_buffering_and_collage_creation(self):
        media_group_id = "album_12345"
        m1 = album_photo(media_group_id, 101, image_bytes(200, 400, (255, 0, 0)))
        # The second photo carries the caption
        m2 = album_photo(media_group_id, 102, image_bytes(300, 400, (0, 255, 0)),
                         caption="Titolo: Sessione Speciale D&D\nQuando: Sabato 05-09-2026 ore 21:00\nPosti liberi: 4/5\nMaster: Gandalf")
        m3 = album_photo(media_group_id, 103, image_bytes(400, 400, (0, 0, 255)))
        context = make_context()

        parsed = {
            "is_event": True,
            "title": "Sessione Speciale D&D",
            "date": "Sabato 05-09-2026 21:00",
            "normalized_date": "05-09-2026",
            "seats": "4/4",
            "max_seats": 4,
            "booked_seats": 0,
        }
        with as_admin_chat(PUBLIC_CHANNEL_ID=PUBLIC_CHANNEL_ID, DATA_DIR=self.temp_dir.name), \
             patch("bot.handlers.albums.asyncio.sleep", side_effect=skip_debounce(media_group_id)), \
             patch("bot.handlers.extraction.parse_event_message", return_value=parsed):
            for message in (m1, m2, m3):
                await process_message(make_update(message=message), context)
            await wait_for_album(media_group_id)

        # 1. All 3 messages were deleted from the public channel
        m1.delete.assert_called_once()
        m2.delete.assert_called_once()
        m3.delete.assert_called_once()

        # 2. The media group entry was cleared from memory
        self.assertNotIn(media_group_id, media_groups)

        # 3. The event was inserted into the DB
        with db.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            events = conn.cursor().execute("SELECT * FROM events").fetchall()
        self.assertEqual(len(events), 1)
        event = events[0]

        # 4. image_path points to the saved collage with the 'event_' prefix
        self.assertIsNotNone(event["image_path"])
        self.assertTrue(os.path.basename(event["image_path"]).startswith("event_"))
        self.assertTrue(os.path.exists(event["image_path"]))

        # 5. The saved image is a horizontal collage
        with Image.open(event["image_path"]) as saved_img:
            self.assertEqual(saved_img.height, 400)
            self.assertEqual(saved_img.width, 200 + 300 + 400)  # 900

    async def test_media_group_without_caption_ignored(self):
        media_group_id = "album_nocaption"
        m1 = album_photo(media_group_id, 201, image_bytes(100, 100, (255, 0, 0)))

        with patched_config(PUBLIC_CHANNEL_ID=PUBLIC_CHANNEL_ID), \
             patch("bot.handlers.albums.asyncio.sleep", side_effect=skip_debounce(media_group_id)), \
             patch("bot.handlers.albums.handle_event_extraction") as mock_extract:
            await process_message(make_update(message=m1), make_context())
            await wait_for_album(media_group_id)

            # Messages without caption are not events and must NOT be deleted from the public channel
            m1.delete.assert_not_called()
            mock_extract.assert_not_called()


class TestAdminMediaGroupCache(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        admin_media_groups.clear()
        self.addCleanup(admin_media_groups.clear)

    async def test_cache_admin_media_group_and_cleanup(self):
        # Two messages belonging to the same media group
        update1 = make_update(message=make_message(caption="Didascalia dell'album", message_id=100,
                                                   media_group_id="mg_album_1", photo=[telegram_photo(b"image_1_data")]))
        update2 = make_update(message=make_message(message_id=101, media_group_id="mg_album_1",
                                                   photo=[telegram_photo(b"image_2_data")]))
        context = make_context()

        await cache_admin_media_group(update1, context)
        await cache_admin_media_group(update2, context)

        self.assertIn("mg_album_1", admin_media_groups)
        entry = admin_media_groups["mg_album_1"]
        self.assertEqual(len(entry["images"]), 2)
        self.assertEqual(entry["images"][100], bytearray(b"image_1_data"))
        self.assertEqual(entry["images"][101], bytearray(b"image_2_data"))
        self.assertEqual(entry["captions"][100], "Didascalia dell'album")

        # Entries older than max_age_seconds are cleaned up
        cleanup_admin_media_cache(now=entry["last_received"] + 4000, max_age_seconds=3600)
        self.assertNotIn("mg_album_1", admin_media_groups)


class TestExtractImageBytes(unittest.IsolatedAsyncioTestCase):
    async def test_extract_image_bytes_from_document_mime(self):
        doc = telegram_photo(b"doc_img")
        doc.mime_type = "image/png"
        update = make_update(document=doc)

        res = await extract_image_bytes_from_update(update)
        self.assertEqual(res, bytearray(b"doc_img"))


if __name__ == "__main__":
    unittest.main()
