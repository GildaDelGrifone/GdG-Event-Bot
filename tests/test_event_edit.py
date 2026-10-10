import asyncio
from datetime import datetime
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import core.db as db
from core import config


class TestEventEditImageAndDiscard(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = self.test_db_path
        db.init_db()

        self.initial_event = {
            "title": "Old Event",
            "date": "Venerdì 04-09-2026 21:00",
            "normalized_date": "04-09-2026",
            "system": "D&D 5e",
            "host": "Old Host",
            "seats": "4/4",
            "booked_seats": 0,
            "max_seats": 4,
            "description": "Old Desc",
            "status": "pending",
            "image_path": None,
        }
        self.event_id = db.insert_event(self.initial_event, None, "test text")

    def tearDown(self):
        self.temp_dir.cleanup()
        config.DB_PATH = self.orig_db_path

    async def test_delete_event_cleans_event_and_reservations(self):
        from core.db import delete_event, get_event, get_reservations_for_event, book_seat

        book_seat(self.event_id, 12345, "testuser")
        self.assertIsNotNone(get_event(self.event_id))
        self.assertEqual(len(get_reservations_for_event(self.event_id)), 1)

        res = delete_event(self.event_id)
        self.assertTrue(res)
        self.assertIsNone(get_event(self.event_id))
        self.assertEqual(len(get_reservations_for_event(self.event_id)), 0)

    async def test_discard_event_callback_deletes_event_and_file(self):
        from bot.callbacks.router import handle_callback_query
        from core.db import get_event

        img_file = os.path.join(self.temp_dir.name, "dummy_event.png")
        with open(img_file, "wb") as f:
            f.write(b"dummy")
        db.update_event_field(self.event_id, "image_path", img_file)

        update = MagicMock()
        query = MagicMock()
        query.data = f"discard_event_{self.event_id}"
        query.message.caption = "Event Review Message"
        query.message.photo = True
        query.answer = AsyncMock()
        query.edit_message_caption = AsyncMock()
        update.callback_query = query
        context = MagicMock()

        await handle_callback_query(update, context)

        self.assertFalse(os.path.exists(img_file))
        self.assertIsNone(get_event(self.event_id))
        query.edit_message_caption.assert_called_once()
        self.assertIn("❌ SCARTATO", query.edit_message_caption.call_args.kwargs.get("caption", ""))

    async def test_event_edit_image_single_photo_reply(self):
        from bot.handlers.edit import event_edit_command
        from core.db import get_event

        old_img = os.path.join(self.temp_dir.name, "old_image.png")
        with open(old_img, "wb") as f:
            f.write(b"old")
        db.update_event_field(self.event_id, "image_path", old_img)

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = None
        update.message.caption = "/event_edit_image"
        update.message.media_group_id = None
        update.message.reply_text = AsyncMock()

        p = MagicMock()
        p.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b"new_image_data"))))
        update.message.photo = [p]

        target_msg = MagicMock()
        target_msg.photo = True
        target_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        target_msg.edit_media = AsyncMock()
        update.message.reply_to_message = target_msg

        context = MagicMock()
        new_saved_path = os.path.join(self.temp_dir.name, "new_saved.png")
        with open(new_saved_path, "wb") as f:
            f.write(b"new_image_data")

        with patch("core.config.ADMIN_CHAT_ID", "999"),              patch("bot.handlers.edit.save_image_locally", return_value=new_saved_path),              patch("bot.handlers.edit.update_event_messages", AsyncMock()):

            await event_edit_command(update, context)

        self.assertFalse(os.path.exists(old_img))
        ev = get_event(self.event_id)
        self.assertEqual(ev["image_path"], new_saved_path)
        target_msg.edit_media.assert_called_once()
        update.message.reply_text.assert_called_once()
        self.assertIn("Campo 'image_path' aggiornato con successo", update.message.reply_text.call_args[0][0])

    async def test_event_edit_image_on_text_only_event_replaces_message(self):
        """
        When /event_edit_image is called on an event that previously had NO image,
        target_msg.photo is False. The bot should send a new photo message via reply_photo,
        update admin_message_id in the DB, and delete the old text target_msg.
        """
        from bot.handlers.edit import event_edit_command
        from core.db import get_event, update_event_field

        # Clear existing image on this event
        update_event_field(self.event_id, "image_path", None)

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = None
        update.message.caption = "/event_edit_image"
        update.message.media_group_id = None
        update.message.reply_text = AsyncMock()

        p = MagicMock()
        p.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b"new_image_data"))))
        update.message.photo = [p]

        target_msg = MagicMock()
        target_msg.message_id = 555
        target_msg.photo = False  # Text-only event card
        target_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        new_sent_photo_msg = MagicMock()
        new_sent_photo_msg.message_id = 777
        target_msg.reply_photo = AsyncMock(return_value=new_sent_photo_msg)
        target_msg.delete = AsyncMock()
        target_msg.edit_media = AsyncMock()
        target_msg.edit_text = AsyncMock()

        update.message.reply_to_message = target_msg

        context = MagicMock()
        new_saved_path = os.path.join(self.temp_dir.name, "new_saved_for_text_event.png")
        with open(new_saved_path, "wb") as f:
            f.write(b"new_image_data")

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.edit.save_image_locally", return_value=new_saved_path), \
             patch("bot.handlers.edit.update_event_messages", AsyncMock()):

            await event_edit_command(update, context)

        ev = get_event(self.event_id)
        self.assertEqual(ev["image_path"], new_saved_path)
        self.assertEqual(ev["admin_message_id"], 777)

        target_msg.reply_photo.assert_called_once()
        target_msg.delete.assert_called_once()
        target_msg.edit_media.assert_not_called()
        target_msg.edit_text.assert_not_called()

        update.message.reply_text.assert_called_once()
        self.assertIn("Campo 'image_path' aggiornato con successo", update.message.reply_text.call_args[0][0])

    async def test_event_edit_image_with_event_id_argument(self):
        from bot.handlers.edit import event_edit_command
        from core.db import get_event

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = f"/event_edit_image {self.event_id}"
        update.message.caption = None
        update.message.media_group_id = None
        update.message.photo = None
        update.message.reply_text = AsyncMock()

        photo_msg = MagicMock()
        p = MagicMock()
        p.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b"photo_from_reply"))))
        photo_msg.photo = [p]
        photo_msg.reply_markup = None
        update.message.reply_to_message = photo_msg

        context = MagicMock()
        new_path = os.path.join(self.temp_dir.name, "new_from_arg.png")
        with open(new_path, "wb") as f:
            f.write(b"photo_from_reply")

        with patch("core.config.ADMIN_CHAT_ID", "999"),              patch("bot.handlers.edit.save_image_locally", return_value=new_path),              patch("bot.handlers.edit.update_event_messages", AsyncMock()):

            await event_edit_command(update, context)

        ev = get_event(self.event_id)
        self.assertEqual(ev["image_path"], new_path)
        update.message.reply_text.assert_called_once()
        self.assertIn("aggiornato con successo", update.message.reply_text.call_args[0][0])

    async def test_event_edit_image_media_group_album(self):
        from bot.handlers.edit import event_edit_command
        from bot.handlers.albums import admin_media_groups
        from core.db import get_event

        admin_media_groups["album_edit_test"] = {
            "images": {
                301: bytearray(b"img1"),
                302: bytearray(b"img2")
            },
            "captions": {},
            "last_received": 0.0,
            "pending_downloads": 0
        }

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.caption = "/event_edit_image"
        update.message.text = None
        update.message.media_group_id = "album_edit_test"
        update.message.photo = None
        update.message.reply_text = AsyncMock()

        target_msg = MagicMock()
        target_msg.photo = True
        target_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        target_msg.edit_media = AsyncMock()
        update.message.reply_to_message = target_msg

        context = MagicMock()
        new_path = os.path.join(self.temp_dir.name, "collage.png")
        with open(new_path, "wb") as f:
            f.write(b"collage")

        with patch("core.config.ADMIN_CHAT_ID", "999"),              patch("bot.handlers.albums.create_collage_from_bytes", return_value=b"stitched_bytes") as mock_collage,              patch("bot.handlers.edit.save_image_locally", return_value=new_path),              patch("bot.handlers.edit.update_event_messages", AsyncMock()):

            await event_edit_command(update, context)

        mock_collage.assert_called_once_with([bytearray(b"img1"), bytearray(b"img2")])
        ev = get_event(self.event_id)
        self.assertEqual(ev["image_path"], new_path)

    async def test_event_edit_image_media_group_concurrent_arrival_waits_for_all_photos(self):
        """
        Simulate an admin sending an album with 3 photos where the 1st photo carries
        /event_edit_image <event_id> as caption.
        As the edit command begins, photo 2 and photo 3 arrive with slight delays.
        The handler must wait for the album photos, stitch all 3 into a collage,
        and update the event's image.
        """
        from bot.handlers.albums import cache_admin_media_group, admin_media_groups
        from bot.handlers.edit import event_edit_command
        from core.db import get_event

        admin_media_groups.clear()
        mg_id = "concurrent_album_edit_test"

        # Setup Update 1 (first photo in album, has caption /event_edit_image <id>)
        update1 = MagicMock()
        update1.effective_chat.id = 999
        msg1 = MagicMock()
        msg1.message_id = 1001
        msg1.media_group_id = mg_id
        msg1.caption = f"/event_edit_image {self.event_id}"
        msg1.text = None
        msg1.reply_to_message = None
        msg1.reply_text = AsyncMock()
        photo1_file = MagicMock()
        photo1_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"photo1_raw"))
        photo1_mock = MagicMock()
        photo1_mock.get_file = AsyncMock(return_value=photo1_file)
        msg1.photo = [photo1_mock]
        msg1.document = None
        update1.message = msg1
        update1.effective_message = msg1

        # Setup Update 2 (second photo in album, no caption)
        update2 = MagicMock()
        update2.effective_chat.id = 999
        msg2 = MagicMock()
        msg2.message_id = 1002
        msg2.media_group_id = mg_id
        msg2.caption = None
        msg2.text = None
        msg2.reply_to_message = None
        photo2_file = MagicMock()
        photo2_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"photo2_raw"))
        photo2_mock = MagicMock()
        photo2_mock.get_file = AsyncMock(return_value=photo2_file)
        msg2.photo = [photo2_mock]
        msg2.document = None
        update2.message = msg2
        update2.effective_message = msg2

        # Setup Update 3 (third photo as image document in album, no caption)
        update3 = MagicMock()
        update3.effective_chat.id = 999
        msg3 = MagicMock()
        msg3.message_id = 1003
        msg3.media_group_id = mg_id
        msg3.caption = None
        msg3.text = None
        msg3.reply_to_message = None
        doc3_file = MagicMock()
        doc3_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"photo3_raw"))
        msg3.photo = None
        msg3.document = MagicMock()
        msg3.document.mime_type = "image/png"
        msg3.document.get_file = AsyncMock(return_value=doc3_file)
        update3.message = msg3
        update3.effective_message = msg3

        context = MagicMock()
        new_path = os.path.join(self.temp_dir.name, "concurrent_collage.png")
        with open(new_path, "wb") as f:
            f.write(b"concurrent_collage")

        # Simulate concurrent arrival:
        # 1. Update 1 is cached in group -1
        await cache_admin_media_group(update1, context)

        # 2. Asynchronously run delayed arrival of update 2 and update 3
        async def arrive_subsequent_updates():
            await asyncio.sleep(0.15)
            await cache_admin_media_group(update2, context)
            await asyncio.sleep(0.15)
            await cache_admin_media_group(update3, context)

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.albums.create_collage_from_bytes", return_value=b"stitched_3_images") as mock_collage, \
             patch("bot.handlers.edit.save_image_locally", return_value=new_path), \
             patch("bot.handlers.edit.update_event_messages", AsyncMock()):

            task_arrive = asyncio.create_task(arrive_subsequent_updates())
            task_cmd = asyncio.create_task(event_edit_command(update1, context))
            await asyncio.gather(task_arrive, task_cmd)

        mock_collage.assert_called_once_with([bytearray(b"photo1_raw"), bytearray(b"photo2_raw"), bytearray(b"photo3_raw")])
        ev = get_event(self.event_id)
        self.assertEqual(ev["image_path"], new_path)

    async def test_event_edit_image_waits_for_media_group_entry_if_called_early(self):
        """
        If event_edit_command starts before cache_admin_media_group registers the
        entry in admin_media_groups, get_media_group_data_from_cache should wait
        until the entry is created rather than immediately returning None.
        """
        from bot.handlers.albums import cache_admin_media_group, admin_media_groups
        from bot.handlers.edit import event_edit_command
        from core.db import get_event

        admin_media_groups.clear()
        mg_id = "early_entry_test"

        update1 = MagicMock()
        update1.effective_chat.id = 999
        msg1 = MagicMock()
        msg1.message_id = 2001
        msg1.media_group_id = mg_id
        msg1.caption = f"/event_edit_image {self.event_id}"
        msg1.text = None
        msg1.reply_to_message = None
        msg1.reply_text = AsyncMock()
        photo1_file = MagicMock()
        photo1_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"early_raw1"))
        photo1_mock = MagicMock()
        photo1_mock.get_file = AsyncMock(return_value=photo1_file)
        msg1.photo = [photo1_mock]
        msg1.document = None
        update1.message = msg1
        update1.effective_message = msg1

        update2 = MagicMock()
        update2.effective_chat.id = 999
        msg2 = MagicMock()
        msg2.message_id = 2002
        msg2.media_group_id = mg_id
        msg2.caption = None
        msg2.text = None
        msg2.reply_to_message = None
        photo2_file = MagicMock()
        photo2_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"early_raw2"))
        photo2_mock = MagicMock()
        photo2_mock.get_file = AsyncMock(return_value=photo2_file)
        msg2.photo = [photo2_mock]
        msg2.document = None
        update2.message = msg2
        update2.effective_message = msg2

        context = MagicMock()
        new_path = os.path.join(self.temp_dir.name, "early_collage.png")
        with open(new_path, "wb") as f:
            f.write(b"early_collage")

        # Note: we do NOT call cache_admin_media_group(update1) beforehand!
        # Both updates arrive slightly after event_edit_command starts.
        async def delayed_both_updates():
            await asyncio.sleep(0.1)
            await cache_admin_media_group(update1, context)
            await asyncio.sleep(0.15)
            await cache_admin_media_group(update2, context)

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.albums.create_collage_from_bytes", return_value=b"early_stitched") as mock_collage, \
             patch("bot.handlers.edit.save_image_locally", return_value=new_path), \
             patch("bot.handlers.edit.update_event_messages", AsyncMock()):

            task_arrive = asyncio.create_task(delayed_both_updates())
            task_cmd = asyncio.create_task(event_edit_command(update1, context))
            await asyncio.gather(task_arrive, task_cmd)

        mock_collage.assert_called_once_with([bytearray(b"early_raw1"), bytearray(b"early_raw2")])
        ev = get_event(self.event_id)
        self.assertEqual(ev["image_path"], new_path)

    async def test_event_edit_image_missing_photo_shows_error(self):
        from bot.handlers.edit import event_edit_command

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = "/event_edit_image"
        update.message.caption = None
        update.message.media_group_id = None
        update.message.photo = None
        update.message.reply_text = AsyncMock()

        target_msg = MagicMock()
        target_msg.photo = False
        target_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        update.message.reply_to_message = target_msg

        context = MagicMock()
        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await event_edit_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Devi allegare un'immagine", update.message.reply_text.call_args[0][0])

    async def test_event_edit_on_discarded_event_reports_not_found(self):
        from bot.handlers.edit import event_edit_command
        from core.db import delete_event

        delete_event(self.event_id)

        update = MagicMock()
        update.effective_chat.id = 999
        update.message = MagicMock()
        update.message.text = "/event_edit_title Nuovo Titolo"
        update.message.caption = None
        update.message.reply_text = AsyncMock()

        target_msg = MagicMock()
        target_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        update.message.reply_to_message = target_msg
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"):
            await event_edit_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("non trovato nel database", update.message.reply_text.call_args[0][0])
    def test_extract_event_id_from_reply_various_formats(self):
        from bot.common.parsing import extract_event_id_from_reply

        # 1. Button callback formats
        prefixes = ["publish_event_42", "cancel_event_42", "book_42", "unbook_42", "manage_subs_42", "sub_inc_42_1"]
        for p in prefixes:
            msg = MagicMock()
            btn = MagicMock(callback_data=p)
            msg.reply_markup.inline_keyboard = [[btn]]
            msg.caption = None
            msg.text = None
            msg.message_id = 9999
            self.assertEqual(extract_event_id_from_reply(msg), 42)

        # 2. Caption/text regex
        msg_text = MagicMock()
        msg_text.reply_markup = None
        msg_text.caption = None
        msg_text.text = "Modifica per evento #42"
        msg_text.message_id = 9999
        self.assertEqual(extract_event_id_from_reply(msg_text), 42)

        msg_hash = MagicMock()
        msg_hash.reply_markup = None
        msg_hash.caption = "#42 Dettagli tavolo"
        msg_hash.text = None
        msg_hash.message_id = 9999
        self.assertEqual(extract_event_id_from_reply(msg_hash), 42)

        # 3. DB admin_message_id
        db.update_event_field(self.event_id, "admin_message_id", 8888)
        msg_admin = MagicMock()
        msg_admin.reply_markup = None
        msg_admin.caption = None
        msg_admin.text = "Messaggio admin senza riferimenti"
        msg_admin.message_id = 8888
        self.assertEqual(extract_event_id_from_reply(msg_admin), self.event_id)

    async def test_extract_image_bytes_from_document_mime(self):
        from bot.handlers.albums import extract_image_bytes_from_update

        update = MagicMock()
        update.message.media_group_id = None
        update.message.photo = None
        doc = MagicMock()
        doc.mime_type = "image/png"
        doc.get_file = AsyncMock(return_value=MagicMock(download_as_bytearray=AsyncMock(return_value=bytearray(b"doc_img"))))
        update.message.document = doc
        update.message.reply_to_message = None

        res = await extract_image_bytes_from_update(update)
        self.assertEqual(res, bytearray(b"doc_img"))

    def test_caption_command_matching_and_handler_registration(self):
        from telegram.ext import filters
        from telegram import Update, Message, Chat, User
        import datetime

        regex_filter = filters.CaptionRegex(r"^/event_edit_")
        m = Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=Chat(id=1, type="group"),
            from_user=User(id=1, is_bot=False, first_name="User"),
            caption="/event_edit_image"
        )
        u = Update(update_id=1, message=m)
        self.assertTrue(regex_filter.check_update(u))

        # CommandHandler must NOT match message captions (by design of PTB)
        from telegram.ext import CommandHandler
        ch = CommandHandler("event_edit_image", lambda u, c: None)
        self.assertFalse(ch.check_update(u))

    async def test_handle_event_extraction_uses_final_form_with_emojis(self):
        from bot.handlers.extraction import handle_event_extraction
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        sent_mock = MagicMock()
        sent_mock.message_id = 777
        context.bot.send_message.return_value = sent_mock

        parsed_data = {
            "is_event": True,
            "title": "Avventura Stellare",
            "date": "Venerdì 25-12-2026 21:00",
            "normalized_date": "25-12-2026",
            "system": "Starfinder",
            "host": "Capitano",
            "seats": "5/5",
            "booked_seats": 0,
            "max_seats": 5,
            "description": "Viaggio nello spazio profondo.",
            "is_roleplay": True,
        }

        with patch("bot.handlers.extraction.parse_event_message", return_value=parsed_data), \
             patch("core.config.ADMIN_CHAT_ID", "999"):
            success = await handle_event_extraction(
                text="Evento Starfinder",
                image_bytes=None,
                context=context,
                is_manual_trigger=True,
            )

        self.assertTrue(success)
        context.bot.send_message.assert_called_once()
        sent_kwargs = context.bot.send_message.call_args.kwargs
        text = sent_kwargs.get("text", "")

        self.assertIn("📣 <b>Avventura Stellare</b>", text)
        self.assertIn("🎲 Sistema: Starfinder", text)
        self.assertIn("👑 Master: Capitano", text)
        self.assertIn("🪑 Posti: 5/5", text)
        self.assertEqual(sent_kwargs.get("parse_mode"), "HTML")

        # Verify admin_message_id was stored in DB
        ev = db.get_event(self.event_id + 1)
        self.assertEqual(ev.get("admin_message_id"), 777)

    async def test_handle_event_extraction_warns_on_caption_over_1024_chars(self):
        from bot.handlers.extraction import handle_event_extraction
        context = MagicMock()
        sent_mock = MagicMock()
        sent_mock.message_id = 888
        context.bot.send_photo = AsyncMock(return_value=sent_mock)

        long_desc = "X" * 1100
        parsed_data = {
            "is_event": True,
            "title": "Evento Lunghissimo",
            "date": "Venerdì 25-12-2026 21:00",
            "normalized_date": "25-12-2026",
            "system": "D&D",
            "host": "Master",
            "seats": "4/4",
            "booked_seats": 0,
            "max_seats": 4,
            "description": long_desc,
        }

        with patch("bot.handlers.extraction.parse_event_message", return_value=parsed_data), \
             patch("core.config.ADMIN_CHAT_ID", "999"):
            success = await handle_event_extraction(
                text="Evento con testo lunghissimo",
                image_bytes=b"dummy_image_data",
                context=context,
                is_manual_trigger=True,
            )

        self.assertTrue(success)
        context.bot.send_photo.assert_called_once()
        caption = context.bot.send_photo.call_args.kwargs.get("caption", "")

        self.assertIn("🚨 ATTENZIONE LIMITE CARATTERI:", caption)
        self.assertIn("IL TESTO DELL'EVENTO SUPERA I 1024 CARATTERI", caption)
        self.assertLessEqual(len(caption), 1024)


    def test_main_admin_handlers_configured_block_false(self):
        from main import main
        from bot.handlers.edit import event_edit_command
        from bot.handlers.ingestion import manual_trigger_command
        from bot.handlers.albums import cache_admin_media_group

        added_handlers = []
        mock_app = MagicMock()
        mock_app.add_handler.side_effect = lambda h, group=0: added_handlers.append((h, group))
        mock_builder = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.post_init.return_value = mock_builder
        mock_builder.post_shutdown.return_value = mock_builder
        mock_builder.build.return_value = mock_app

        with patch("main.init_db"), \
             patch("main.Application.builder", return_value=mock_builder), \
             patch("main.ADMIN_CHAT_ID", "999"), \
             patch("main.TELEGRAM_BOT_TOKEN", "fake_token"):
            try:
                main()
            except Exception:
                pass

        matched = 0
        for handler, group in added_handlers:
            cb = getattr(handler, "callback", None)
            if cb in (event_edit_command, manual_trigger_command, cache_admin_media_group):
                self.assertFalse(handler.block, f"Handler {handler} with callback {cb} should have block=False")
                matched += 1

        # We expect:
        # event_process (1), ep (1), 10 edit_cmds (10), CaptionRegex event_edit_ (1), CaptionRegex ep (1), cache_admin_media_group (1)
        self.assertGreaterEqual(matched, 15)

    async def test_post_init_sets_bot_commands(self):
        from main import post_init
        from telegram import BotCommandScopeDefault, BotCommandScopeChat

        mock_bot = MagicMock()
        mock_bot.set_my_commands = AsyncMock()
        mock_app = MagicMock()
        mock_app.bot = mock_bot

        with patch("main.start_scheduler"), \
             patch("main.ADMIN_CHAT_ID", "-100123456"):
            await post_init(mock_app)

        self.assertEqual(mock_bot.set_my_commands.call_count, 2)

        # Check call 1: Default scope
        call1 = mock_bot.set_my_commands.call_args_list[0]
        cmds1, kwargs1 = call1[0][0], call1[1]
        self.assertIsInstance(kwargs1.get("scope"), BotCommandScopeDefault)
        self.assertTrue(any(c.command == "start" for c in cmds1))

        # Check call 2: Admin Chat scope
        call2 = mock_bot.set_my_commands.call_args_list[1]
        cmds2, kwargs2 = call2[0][0], call2[1]
        self.assertIsInstance(kwargs2.get("scope"), BotCommandScopeChat)
        self.assertEqual(kwargs2["scope"].chat_id, -100123456)
        cmd_names = [c.command for c in cmds2]
        self.assertIn("event_next", cmd_names)
        self.assertIn("event_edit_title", cmd_names)
        self.assertIn("event_edit_date", cmd_names)
        self.assertNotIn("event_edit_normalized_date", cmd_names)

        # Check syntax in description
        title_cmd = next(c for c in cmds2 if c.command == "event_edit_title")
        self.assertIn("<Titolo>", title_cmd.description)
        date_cmd = next(c for c in cmds2 if c.command == "event_edit_date")
        self.assertIn("<DD-MM-YYYY HH:MM>", date_cmd.description)



class TestEventNextCommand(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = self.test_db_path
        db.init_db()

    def tearDown(self):
        config.DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()

    async def test_event_next_command_non_admin_ignored(self):
        from bot.handlers.public import event_next_command
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "-100999999"):
            await event_next_command(update, context)

        update.message.reply_text.assert_not_called()

    async def test_event_next_command_no_events(self):
        from bot.handlers.public import event_next_command
        update = MagicMock()
        update.effective_chat.id = -100999999
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "-100999999"):
            await event_next_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Nessun evento in programma", update.message.reply_text.call_args[0][0])

    async def test_event_next_command_lists_today_and_future_events(self):
        from bot.handlers.public import event_next_command
        today_str = datetime.now().strftime("%d-%m-%Y")

        # 1. Past event (should NOT be included)
        ev_past_id = db.insert_event({
            "title": "Evento Passato",
            "date": "01-01-2020",
            "normalized_date": "01-01-2020",
        }, None, "raw past")
        db.update_event_status(ev_past_id, "approved")

        # 2. Today's event (SHOULD be included)
        ev_today_id = db.insert_event({
            "title": "Evento Di Oggi",
            "date": f"Oggi {today_str} ore 21:00",
            "normalized_date": today_str,
        }, None, "raw today")
        db.update_event_status(ev_today_id, "approved")
        db.update_event_field(ev_today_id, "admin_message_id", 301)
        db.update_discussion_message_info(ev_today_id, 401, "-100888888")

        # 3. Future pending event (SHOULD be included)
        ev_future_id = db.insert_event({
            "title": "Evento Futuro",
            "date": "Venerdì 25-12-2099",
            "normalized_date": "25-12-2099",
        }, None, "raw future")
        db.update_event_field(ev_future_id, "admin_message_id", 302)

        update = MagicMock()
        update.effective_chat.id = -100999999
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "-100999999"), \
             patch("core.config.DISCUSSION_GROUP_ID", "-100888888"):
            await event_next_command(update, context)

        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]

        self.assertNotIn("Evento Passato", reply_text)
        self.assertIn("Evento Di Oggi", reply_text)
        self.assertIn("Evento Futuro", reply_text)
        self.assertIn("[In attesa di approvazione]", reply_text)
        self.assertIn('https://t.me/c/999999/301', reply_text)
        self.assertIn('https://t.me/c/999999/302', reply_text)
        self.assertIn('https://t.me/c/888888/401', reply_text)
        self.assertIn('/event_subs &lt;id&gt;', reply_text)
        self.assertNotIn(f'(/event_subs {ev_today_id})', reply_text)
        self.assertIn('👥 Iscritti</a> (Nessun limite)', reply_text)
        self.assertIn(f'start=subs_{ev_today_id}', reply_text)

    async def test_event_next_command_public_private_chat_allowed(self):
        from bot.handlers.public import event_next_command
        update = MagicMock()
        update.effective_chat.id = 55555
        update.effective_chat.type = "private"
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "-100999999"), \
             patch("core.config.DISCUSSION_GROUP_ID", "-100888888"):
            await event_next_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Nessun evento in programma", update.message.reply_text.call_args[0][0])

    async def test_event_next_command_discussion_group_allowed(self):
        from bot.handlers.public import event_next_command
        update = MagicMock()
        update.effective_chat.id = -100888888
        update.effective_chat.type = "supergroup"
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "-100999999"), \
             patch("core.config.DISCUSSION_GROUP_ID", "-100888888"), \
             patch("core.config.ALLOW_GROUP_EVENT_NEXT", True):
            await event_next_command(update, context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Nessun evento in programma", update.message.reply_text.call_args[0][0])

    async def test_event_next_command_discussion_group_disabled(self):
        from bot.handlers.public import event_next_command
        update = MagicMock()
        update.effective_chat.id = -100888888
        update.effective_chat.type = "supergroup"
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("core.config.ADMIN_CHAT_ID", "-100999999"), \
             patch("core.config.DISCUSSION_GROUP_ID", "-100888888"), \
             patch("core.config.ALLOW_GROUP_EVENT_NEXT", False):
            await event_next_command(update, context)

        update.message.reply_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
