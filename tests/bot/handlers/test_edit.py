import asyncio
import os
import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import core.db as db
from bot.common.parsing import UNLIMITED_SEATS_DISPLAY
from bot.handlers.albums import admin_media_groups, cache_admin_media_group
from bot.handlers.edit import EditInputError, edit_seats, event_edit_command
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import admin_card, admin_update, make_context, make_message, make_update, telegram_photo


class TestEditSeats(unittest.IsolatedAsyncioTestCase):
    async def test_edit_seats_variants(self):
        with patch("bot.handlers.edit.update_event_field", return_value=True) as upd:
            await edit_seats(None, 1, {"booked_seats": 1}, "2/5")
            self.assertEqual(
                [c.args for c in upd.call_args_list],
                [(1, "booked_seats", 3), (1, "max_seats", 5), (1, "seats", "2/5")],
            )

            upd.reset_mock()
            await edit_seats(None, 1, {"booked_seats": 1}, "4")
            self.assertEqual([c.args for c in upd.call_args_list], [(1, "max_seats", 4), (1, "seats", "3/4")])

            upd.reset_mock()
            await edit_seats(None, 1, {}, "null")
            self.assertEqual([c.args for c in upd.call_args_list],
                             [(1, "max_seats", None), (1, "seats", UNLIMITED_SEATS_DISPLAY)])

            with self.assertRaises(EditInputError):
                await edit_seats(None, 1, {}, "tanti")


class OldEventMixin(TempDBMixin):
    """A pending event ("Old Event") plus the admin card replying to it."""

    def setUp(self):
        super().setUp()
        self.event_id = create_event(
            original_text="test text", title="Old Event", date="Venerdì 04-09-2026 21:00",
            normalized_date="04-09-2026", system="D&D 5e", host="Old Host", seats="4/4", booked_seats=0,
            max_seats=4, description="Old Desc",
        )
        self.context = make_context()

    def _file(self, name, data):
        path = os.path.join(self.temp_dir.name, name)
        with open(path, "wb") as f:
            f.write(data)
        return path


class TestEventEditImage(OldEventMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        admin_media_groups.clear()
        self.addCleanup(admin_media_groups.clear)

    def _edit_patches(self, saved_path):
        return (patch("bot.handlers.edit.save_image_locally", return_value=saved_path),
                patch("bot.handlers.edit.update_event_messages", AsyncMock()))

    async def _run(self, update, saved_path):
        save_patch, update_patch = self._edit_patches(saved_path)
        with as_admin_chat(), save_patch, update_patch:
            await event_edit_command(update, self.context)

    def _album_message(self, mg_id, message_id, data, caption=None, as_document=False):
        message = make_message(caption=caption, message_id=message_id, media_group_id=mg_id,
                               photo=None if as_document else [telegram_photo(data)])
        if as_document:
            message.document = telegram_photo(data)
            message.document.mime_type = "image/png"
        return make_update(message=message)

    async def test_event_edit_image_single_photo_reply(self):
        old_img = self._file("old_image.png", b"old")
        db.update_event_field(self.event_id, "image_path", old_img)
        target_msg = admin_card(self.event_id, photo=True)
        update = admin_update(caption="/event_edit_image", reply_to=target_msg,
                              photo=[telegram_photo(b"new_image_data")])
        new_saved_path = self._file("new_saved.png", b"new_image_data")

        await self._run(update, new_saved_path)

        self.assertFalse(os.path.exists(old_img))
        self.assertEqual(db.get_event(self.event_id)["image_path"], new_saved_path)
        target_msg.edit_media.assert_called_once()
        update.message.reply_text.assert_called_once()
        self.assertIn("Campo 'image_path' aggiornato con successo", update.message.reply_text.call_args[0][0])

    async def test_event_edit_image_on_text_only_event_replaces_message(self):
        """
        /event_edit_image on an event that had NO image (text-only admin card, target_msg.photo falsy):
        the bot sends a new photo message via reply_photo, stores its id as admin_message_id and deletes
        the old text card.
        """
        db.update_event_field(self.event_id, "image_path", None)
        target_msg = admin_card(self.event_id, message_id=555)  # Text-only event card
        target_msg.reply_photo.return_value = MagicMock(message_id=777)
        update = admin_update(caption="/event_edit_image", reply_to=target_msg,
                              photo=[telegram_photo(b"new_image_data")])
        new_saved_path = self._file("new_saved_for_text_event.png", b"new_image_data")

        await self._run(update, new_saved_path)

        ev = db.get_event(self.event_id)
        self.assertEqual(ev["image_path"], new_saved_path)
        self.assertEqual(ev["admin_message_id"], 777)

        target_msg.reply_photo.assert_called_once()
        target_msg.delete.assert_called_once()
        target_msg.edit_media.assert_not_called()
        target_msg.edit_text.assert_not_called()

        update.message.reply_text.assert_called_once()
        self.assertIn("Campo 'image_path' aggiornato con successo", update.message.reply_text.call_args[0][0])

    async def test_event_edit_image_with_event_id_argument(self):
        photo_msg = make_message(photo=[telegram_photo(b"photo_from_reply")])
        photo_msg.reply_markup = None
        update = admin_update(f"/event_edit_image {self.event_id}", reply_to=photo_msg)
        new_path = self._file("new_from_arg.png", b"photo_from_reply")

        await self._run(update, new_path)

        self.assertEqual(db.get_event(self.event_id)["image_path"], new_path)
        update.message.reply_text.assert_called_once()
        self.assertIn("aggiornato con successo", update.message.reply_text.call_args[0][0])

    async def test_event_edit_image_media_group_album(self):
        admin_media_groups["album_edit_test"] = {
            "images": {301: bytearray(b"img1"), 302: bytearray(b"img2")},
            "captions": {},
            "last_received": 0.0,
            "pending_downloads": 0,
        }
        update = admin_update(caption="/event_edit_image", media_group_id="album_edit_test",
                              reply_to=admin_card(self.event_id, photo=True))
        new_path = self._file("collage.png", b"collage")

        with patch("bot.handlers.albums.create_collage_from_bytes", return_value=b"stitched_bytes") as mock_collage:
            await self._run(update, new_path)

        mock_collage.assert_called_once_with([bytearray(b"img1"), bytearray(b"img2")])
        self.assertEqual(db.get_event(self.event_id)["image_path"], new_path)

    async def _run_with_late_album(self, command_update, arrivals, saved_path, collage_bytes):
        """Runs the edit command while `arrivals` (delay, update) are cached concurrently; returns the collage mock."""
        async def arrive():
            for delay, album_update in arrivals:
                await asyncio.sleep(delay)
                await cache_admin_media_group(album_update, self.context)

        save_patch, update_patch = self._edit_patches(saved_path)
        with as_admin_chat(), save_patch, update_patch, \
             patch("bot.handlers.albums.create_collage_from_bytes", return_value=collage_bytes) as mock_collage:
            await asyncio.gather(asyncio.create_task(arrive()),
                                 asyncio.create_task(event_edit_command(command_update, self.context)))
        return mock_collage

    async def test_event_edit_image_media_group_concurrent_arrival_waits_for_all_photos(self):
        """
        An admin sends a 3-photo album whose first photo carries /event_edit_image <event_id> as caption.
        Photos 2 and 3 arrive after the edit command starts; the handler must wait for them, stitch all 3
        into a collage and update the event's image.
        """
        mg_id = "concurrent_album_edit_test"
        update1 = self._album_message(mg_id, 1001, b"photo1_raw", caption=f"/event_edit_image {self.event_id}")
        update2 = self._album_message(mg_id, 1002, b"photo2_raw")
        update3 = self._album_message(mg_id, 1003, b"photo3_raw", as_document=True)  # image sent as a document
        new_path = self._file("concurrent_collage.png", b"concurrent_collage")

        # The first photo is cached before the command runs; the others arrive with small delays
        await cache_admin_media_group(update1, self.context)
        mock_collage = await self._run_with_late_album(update1, [(0.15, update2), (0.15, update3)], new_path,
                                                       b"stitched_3_images")

        mock_collage.assert_called_once_with([bytearray(b"photo1_raw"), bytearray(b"photo2_raw"), bytearray(b"photo3_raw")])
        self.assertEqual(db.get_event(self.event_id)["image_path"], new_path)

    async def test_event_edit_image_waits_for_media_group_entry_if_called_early(self):
        """
        If event_edit_command starts before cache_admin_media_group registers the album in admin_media_groups,
        get_media_group_data_from_cache must wait for the entry instead of returning None immediately.
        """
        mg_id = "early_entry_test"
        update1 = self._album_message(mg_id, 2001, b"early_raw1", caption=f"/event_edit_image {self.event_id}")
        update2 = self._album_message(mg_id, 2002, b"early_raw2")
        new_path = self._file("early_collage.png", b"early_collage")

        # update1 is NOT cached beforehand: both photos arrive slightly after the command starts
        mock_collage = await self._run_with_late_album(update1, [(0.1, update1), (0.15, update2)], new_path,
                                                       b"early_stitched")

        mock_collage.assert_called_once_with([bytearray(b"early_raw1"), bytearray(b"early_raw2")])
        self.assertEqual(db.get_event(self.event_id)["image_path"], new_path)

    async def test_event_edit_image_missing_photo_shows_error(self):
        update = admin_update("/event_edit_image", reply_to=admin_card(self.event_id))

        with as_admin_chat():
            await event_edit_command(update, self.context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Devi allegare un'immagine", update.message.reply_text.call_args[0][0])


class TestEventEditFields(OldEventMixin, unittest.IsolatedAsyncioTestCase):
    async def _edit(self, text):
        update = admin_update(text, reply_to=admin_card(self.event_id))
        with as_admin_chat():
            await event_edit_command(update, self.context)
        return update

    async def test_event_edit_on_discarded_event_reports_not_found(self):
        db.delete_event(self.event_id)

        update = await self._edit("/event_edit_title Nuovo Titolo")

        update.message.reply_text.assert_called_once()
        self.assertIn("non trovato nel database", update.message.reply_text.call_args[0][0])

    async def test_event_edit_extra_add_when_empty(self):
        update = await self._edit("/event_edit_extra_add Prima nota extra")

        self.assertEqual(db.get_event(self.event_id).get("extra_info"), "Prima nota extra")
        update.message.reply_text.assert_called_once()
        self.assertIn("aggiornato con successo", update.message.reply_text.call_args[0][0])

    async def test_event_edit_extra_add_appends_on_new_line(self):
        db.update_event_field(self.event_id, "extra_info", "Nota esistente")

        update = await self._edit("/event_edit_extra_add Nuova nota aggiunta")

        self.assertEqual(db.get_event(self.event_id).get("extra_info"), "Nota esistente\nNuova nota aggiunta")
        update.message.reply_text.assert_called_once()
        self.assertIn("aggiornato con successo", update.message.reply_text.call_args[0][0])

    async def test_event_edit_extra_add_preserves_multiline_text(self):
        db.update_event_field(self.event_id, "extra_info", "Nota base")

        update = await self._edit("/event_edit_extra_add Riga 1\nRiga 2\nRiga 3")

        self.assertEqual(db.get_event(self.event_id).get("extra_info"), "Nota base\nRiga 1\nRiga 2\nRiga 3")
        update.message.reply_text.assert_called_once()
        self.assertIn("aggiornato con successo", update.message.reply_text.call_args[0][0])

    async def test_event_edit_extra_add_empty_value_shows_error(self):
        update = await self._edit("/event_edit_extra_add")

        self.assertFalse(db.get_event(self.event_id).get("extra_info"))
        update.message.reply_text.assert_called_once()
        self.assertIn("specificare il testo", update.message.reply_text.call_args[0][0].lower())

    async def test_event_edit_extra_add_warns_when_caption_size_busts(self):
        # The description is already substantial, so the added extra text pushes the post past 1024 chars
        db.update_event_field(self.event_id, "description", "D" * 800)
        added_text = "E" * 300

        update = await self._edit(f"/event_edit_extra_add {added_text}")

        self.assertEqual(db.get_event(self.event_id).get("extra_info"), added_text)
        # The admin must receive the warning
        all_replies = [call[0][0] for call in update.message.reply_text.call_args_list]
        self.assertTrue(
            any("Attenzione" in r and "1024" in r for r in all_replies),
            f"Expected warning in replies, got: {all_replies}"
        )


class TestEventEditTypeCommand(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.event_id = create_event(status="approved", title="Session 1", date="05-09-2026 21:00", system="Generic",
                                     host="Master DM", is_roleplay=1)
        self.target_msg = admin_card(self.event_id)

    async def _edit_type(self, text):
        update = admin_update(text, reply_to=self.target_msg)
        with as_admin_chat(), patch("bot.handlers.edit.update_event_messages", AsyncMock()) as mock_update_msgs:
            await event_edit_command(update, make_context())
        return update, mock_update_msgs

    async def test_event_edit_type_to_boardgame(self):
        update, mock_update_msgs = await self._edit_type("/event_edit_type boardgame")

        self.assertEqual(db.get_event(self.event_id)["is_roleplay"], 0)
        update.message.reply_text.assert_called_with("✅ Campo 'is_roleplay' aggiornato con successo!")
        mock_update_msgs.assert_called_once()
        self.target_msg.edit_text.assert_called_once()
        self.assertIn("Host: Master DM", self.target_msg.edit_text.call_args.kwargs["text"])

    async def test_event_edit_type_to_rpg(self):
        db.update_event_field(self.event_id, "is_roleplay", 0)

        await self._edit_type("/event_edit_type rpg")

        self.assertEqual(db.get_event(self.event_id)["is_roleplay"], 1)
        self.assertIn("Master: Master DM", self.target_msg.edit_text.call_args.kwargs["text"])

    async def test_event_edit_type_toggle(self):
        self.assertEqual(db.get_event(self.event_id)["is_roleplay"], 1)

        await self._edit_type("/event_edit_type")

        self.assertEqual(db.get_event(self.event_id)["is_roleplay"], 0)

    async def test_event_edit_type_invalid_argument(self):
        # The old version of this test was truncated after building the update; completed with the rejection check
        update, _ = await self._edit_type("/event_edit_type invalido")

        self.assertIn("Tipo non valido", update.message.reply_text.call_args[0][0])
        self.assertEqual(db.get_event(self.event_id)["is_roleplay"], 1)


class TestEventEditDate(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.event_id = create_event(
            original_text="Raw text", message_link="https://t.me/c/123/1", telegram_message_id=5001,
            title="Tavolo GdR", date="Venerdì 04-09-2026 21:00", normalized_date="04-09-2026", system="D&D 5e",
            host="Master DM", seats="4/4", max_seats=4, booked_seats=0, description=None,
        )
        self.reply_msg = admin_card(self.event_id)

    async def _edit_date(self, text, **config_values):
        update = admin_update(text, reply_to=self.reply_msg)
        with as_admin_chat(**config_values), patch("bot.handlers.edit.update_event_messages", AsyncMock()):
            await event_edit_command(update, make_context())
        return update

    async def test_event_edit_date_invalid_format_rejects(self):
        update = await self._edit_date("/event_edit_date domani sera")

        update.message.reply_text.assert_called_once()
        self.assertIn("Formato data non valido", update.message.reply_text.call_args[0][0])
        ev = db.get_event(self.event_id)
        # Event in DB must NOT be changed
        self.assertEqual(ev["date"], "Venerdì 04-09-2026 21:00")
        self.assertEqual(ev["normalized_date"], "04-09-2026")

    async def test_event_edit_date_nonexistent_calendar_date_rejects(self):
        update = await self._edit_date("/event_edit_date 31-02-2026")

        update.message.reply_text.assert_called_once()
        self.assertIn("Formato data non valido", update.message.reply_text.call_args[0][0])
        self.assertEqual(db.get_event(self.event_id)["normalized_date"], "04-09-2026")

    async def test_event_edit_date_valid_dual_sync(self):
        # Sept 5, 2026 is Saturday (Sabato)
        update = await self._edit_date("/event_edit_date 05-09-2026 21:00")

        update.message.reply_text.assert_called_once()
        self.assertIn("aggiornato con successo", update.message.reply_text.call_args[0][0])
        ev = db.get_event(self.event_id)
        # Date must have Italian weekday prepended and normalized_date synced
        self.assertEqual(ev["date"], "Sabato 05-09-2026 21:00")
        self.assertEqual(ev["normalized_date"], "05-09-2026")
        self.reply_msg.edit_text.assert_called_once()

    async def test_event_edit_date_moves_image_and_updates_db(self):
        old_dir = os.path.join(self.temp_dir.name, "2026", "09", "04")
        os.makedirs(old_dir, exist_ok=True)
        img_file = os.path.join(old_dir, "event_test_1.jpg")
        with open(img_file, "wb") as f:
            f.write(b"test image data 1")
        db.update_event_field(self.event_id, "image_path", img_file)

        await self._edit_date("/event_edit_date 09-09-2026 21:00", DATA_DIR=self.temp_dir.name)

        expected_new_path = os.path.join(self.temp_dir.name, "2026", "09", "09", "event_test_1.jpg")
        self.assertEqual(db.get_event(self.event_id)["image_path"], expected_new_path)
        self.assertTrue(os.path.exists(expected_new_path))
        self.assertFalse(os.path.exists(img_file))
        self.assertFalse(os.path.exists(old_dir))

    async def test_event_edit_date_clears_date_anomaly_warning(self):
        # The event starts with a weekday mismatch
        db.update_event_field(self.event_id, "date", "Sabato 04-09-2026")
        db.update_event_field(self.event_id, "normalized_date", "04-09-2026")
        self.reply_msg.text = "🚨 ATTENZIONE ANOMALIE DATA:\n..."

        # The admin corrects the date to a valid future date
        with patch("utils.date_utils.date") as mock_date:
            mock_date.today.return_value = date(2026, 9, 1)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            await self._edit_date("/event_edit_date 04-09-2026 21:00")

        self.reply_msg.edit_text.assert_called_once()
        edited_text = self.reply_msg.edit_text.call_args.kwargs.get("text", "")
        # Warning must be completely gone
        self.assertNotIn("🚨 ATTENZIONE ANOMALIE DATA:", edited_text)
        self.assertIn("Data: Venerdì 04-09-2026 21:00", edited_text)

    async def test_event_edit_date_supports_oggi_and_lun(self):
        ev_id = create_event(original_text="Testo originale", title="Partita di Prova", date="Venerdì 04-09-2026",
                             host="DM", description="Una bella avventura")
        update = admin_update("/event_edit_date oggi", reply_to=admin_card(ev_id, text="Event text"))

        with as_admin_chat():
            await event_edit_command(update, make_context())

        self.assertEqual(db.get_event(ev_id)["normalized_date"], datetime.now().strftime("%d-%m-%Y"))


if __name__ == "__main__":
    unittest.main()
