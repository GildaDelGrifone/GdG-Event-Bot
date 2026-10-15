import unittest
from unittest.mock import AsyncMock, patch

import core.db as db
from bot.handlers.albums import admin_media_groups, media_groups
from bot.handlers.ingestion import manual_trigger_command, process_message
from core.ai_parser import GeminiQuotaError
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin
from tests.support.images import image_bytes
from tests.support.telegram import (
    admin_update,
    channel_message,
    make_context,
    make_message,
    make_update,
    telegram_photo,
)

PUBLIC_CHANNEL_ID = "-100123456789"


def public_post(message_id, **kwargs):
    return channel_message(PUBLIC_CHANNEL_ID, message_id, **kwargs)


def stored_events():
    with db.get_connection() as conn:
        return conn.cursor().execute("SELECT * FROM events").fetchall()


class TestDeferredMessageDeletion(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        media_groups.clear()
        self.addCleanup(media_groups.clear)
        self.context = make_context()

    def channel_config(self):
        return as_admin_chat(PUBLIC_CHANNEL_ID=PUBLIC_CHANNEL_ID)

    async def _process_album(self, media_group_id, messages, parsed):
        """Feeds an album through process_message with the debounce sleep skipped, then awaits its task."""
        async def fast_sleep(_secs):
            if media_group_id in media_groups:
                media_groups[media_group_id]["last_received"] = 0

        with self.channel_config(), \
             patch("bot.handlers.albums.asyncio.sleep", side_effect=fast_sleep), \
             patch("bot.handlers.albums.create_collage_from_bytes", return_value=b"collage"), \
             patch("bot.handlers.extraction.parse_event_message", return_value=parsed) as mock_parser:
            for message in messages:
                await process_message(make_update(message=message), self.context)

            if media_group_id in media_groups and media_groups[media_group_id]["task"]:
                await media_groups[media_group_id]["task"]
        return mock_parser

    async def test_single_message_non_event_preserved_in_channel(self):
        message = public_post(501, text="Descrizione: Avviso ai soci, sabato la sede sarà chiusa per manutenzione.")
        non_event_data = {"is_event": False, "reason": "General announcement about venue closure"}

        with self.channel_config(), \
             patch("bot.handlers.extraction.parse_event_message", return_value=non_event_data) as mock_parser:
            await process_message(make_update(message=message), self.context)

            mock_parser.assert_called_once_with(message.text)
            # Original message in public channel was NOT deleted
            message.delete.assert_not_called()
            # No admin notification was sent
            self.context.bot.send_message.assert_not_called()
            # No event was stored in database
            self.assertEqual(len(stored_events()), 0)

    async def test_single_message_confirmed_event_deleted_from_channel(self):
        message = public_post(
            502, text="Titolo: D&D 5e: Phandelver\nQuando: Sabato 12-09-2026 ore 21:00\nMaster: Gandalf\nPosti liberi: 5")
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
            "description": "Avventura livello 1",
        }

        with self.channel_config(), \
             patch("bot.handlers.extraction.parse_event_message", return_value=event_data) as mock_parser:
            await process_message(make_update(message=message), self.context)

            mock_parser.assert_called_once_with(message.text)
            # Confirmed event MUST be deleted from the public channel
            message.delete.assert_called_once()

    async def test_media_group_non_event_all_messages_preserved(self):
        m1 = public_post(601, media_group_id="album_notice_1", photo=[telegram_photo(b"dummy1")],
                             caption="Descrizione: Nuove miniature per gioco da tavolo arrivate in associazione! Venite a vederle!")
        m2 = public_post(602, media_group_id="album_notice_1", photo=[telegram_photo(b"dummy2")])
        non_event_data = {"is_event": False, "reason": "Showcase of miniatures, not a bookable game session"}

        mock_parser = await self._process_album("album_notice_1", [m1, m2], non_event_data)

        mock_parser.assert_called_once()
        # Neither photo message in the album should be deleted
        m1.delete.assert_not_called()
        m2.delete.assert_not_called()
        # No event stored in DB
        self.assertEqual(len(stored_events()), 0)

    async def test_media_group_confirmed_event_all_messages_deleted(self):
        m1 = public_post(701, media_group_id="album_event_1", photo=[telegram_photo(b"dummy1")],
                             caption="Titolo: Campagna Call of Cthulhu\nQuando: Sabato 19-09-2026 ore 21:00\nPosti liberi: 4")
        m2 = public_post(702, media_group_id="album_event_1", photo=[telegram_photo(b"dummy2")])
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
            "description": "Orrore cosmico",
        }

        mock_parser = await self._process_album("album_event_1", [m1, m2], event_data)

        mock_parser.assert_called_once()
        # Both photo messages in the album MUST be deleted
        m1.delete.assert_called_once()
        m2.delete.assert_called_once()
        # Event stored in DB
        self.assertEqual(len(stored_events()), 1)

    async def test_quota_error_preserves_channel_message(self):
        message = public_post(801, text="Sessione One-shot Cyberpunk Red Sabato 19-09-2026")

        err_text = "429 Your prepayment credits are depleted."
        with self.channel_config(), \
             patch("bot.handlers.extraction.parse_event_message", side_effect=GeminiQuotaError(err_text)):
            await process_message(make_update(message=message), self.context)

            # Channel message preserved because extraction failed
            message.delete.assert_not_called()
            # Admin alerted about quota depletion
            self.context.bot.send_message.assert_called_once()
            self.assertIn("429", self.context.bot.send_message.call_args.kwargs.get("text", ""))
            # No event stored in DB
            self.assertEqual(len(stored_events()), 0)


class TestGeminiQuotaDepletionAlert(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_manual_trigger_command_reports_error_when_quota_depleted(self):
        update = admin_update("/ep Sessione di gioco", message_id=123)
        context = make_context()

        err_text = "429 Your prepayment credits are depleted."
        with patch("bot.handlers.extraction.parse_event_message", side_effect=GeminiQuotaError(err_text)), \
             as_admin_chat():
            await manual_trigger_command(update, context)

        # The bot sends the quota alert...
        context.bot.send_message.assert_called_once_with(
            chat_id="999",
            text="🚨 Errore Gemini AI (Crediti esauriti):\n429 Your prepayment credits are depleted."
        )
        # ...and does NOT reply "Processato il testo inviato."
        update.message.reply_text.assert_not_called()


class TestSinglePhotoIngestion(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        media_groups.clear()
        self.addCleanup(media_groups.clear)

    async def test_single_photo_message_processed_immediately(self):
        b1 = image_bytes(100, 100, (255, 0, 0))
        m1 = public_post(301, caption="Sessione Singola D&D Sabato 05-09-2026 ore 21:00 Posti 4/5",
                         photo=[telegram_photo(b1)])

        async def fake_handle_extraction(*args, **kwargs):
            del_cb = kwargs.get("delete_callback")
            if del_cb:
                await del_cb()
            return True

        with as_admin_chat(PUBLIC_CHANNEL_ID=PUBLIC_CHANNEL_ID), \
             patch("bot.handlers.ingestion.handle_event_extraction", side_effect=fake_handle_extraction) as mock_extract:
            await process_message(make_update(message=m1), make_context())

            m1.delete.assert_called_once()
            self.assertEqual(len(media_groups), 0)
            mock_extract.assert_called_once()
            kwargs = mock_extract.call_args.kwargs
            extracted_text = kwargs.get("text") if kwargs else mock_extract.call_args[0][0]
            extracted_bytes = kwargs.get("image_bytes") if kwargs else mock_extract.call_args[0][1]
            self.assertEqual(extracted_text, m1.caption)
            self.assertEqual(extracted_bytes, bytearray(b1))


class TestAdminMediaGroupManualProcessing(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        admin_media_groups.clear()
        self.addCleanup(admin_media_groups.clear)
        self.context = make_context()

    async def _ep(self, text, target_msg, **patches):
        """Runs `text` (an /ep command) as a reply to target_msg with handle_event_extraction mocked."""
        update = admin_update(text, reply_to=target_msg)
        with as_admin_chat(), \
             patch("bot.handlers.ingestion.handle_event_extraction", new_callable=AsyncMock, return_value=True) as mock_extract:
            await manual_trigger_command(update, self.context)
        return update, mock_extract

    def _album_photo(self, media_group_id, message_id, caption=None, photo=None, link=None):
        message = make_message(caption=caption, message_id=message_id, media_group_id=media_group_id,
                               photo=[photo or telegram_photo(b"unused")])
        message.link = link
        return message

    async def test_manual_trigger_with_cached_media_group_creates_collage(self):
        admin_media_groups["album_test"] = {
            "images": {200: bytearray(b"img_bytes_1"), 201: bytearray(b"img_bytes_2")},
            "captions": {200: "Titolo: Gioco di Ruolo\nData: 10-10-2026 21:00\nSistema: D&D"},
            "last_received": 0.0,
            "pending_downloads": 0,
        }
        # The admin replies /ep to the SECOND photo (message_id 201, which has NO caption)
        target_msg = self._album_photo("album_test", 201, link="https://t.me/c/999/201")

        with patch("bot.handlers.albums.create_collage_from_bytes", return_value=b"stitched_collage_bytes") as mock_collage:
            update, mock_extract = await self._ep("/ep", target_msg)

        mock_collage.assert_called_once_with([bytearray(b"img_bytes_1"), bytearray(b"img_bytes_2")])
        mock_extract.assert_called_once_with(
            "Titolo: Gioco di Ruolo\nData: 10-10-2026 21:00\nSistema: D&D",
            b"stitched_collage_bytes",
            self.context,
            "https://t.me/c/999/201",
            201,
            is_manual_trigger=True,
        )
        update.message.reply_text.assert_called_once_with("Processato il messaggio risposto.")

    async def test_manual_trigger_custom_text_overrides_album_caption(self):
        admin_media_groups["album_test2"] = {
            "images": {300: bytearray(b"img_bytes_A"), 301: bytearray(b"img_bytes_B")},
            "captions": {300: "Didascalia originale"},
            "last_received": 0.0,
            "pending_downloads": 0,
        }
        target_msg = self._album_photo("album_test2", 300, caption="Didascalia originale",
                                       link="https://t.me/c/999/300")

        with patch("bot.handlers.albums.create_collage_from_bytes", return_value=b"collage_custom"):
            _update, mock_extract = await self._ep("/ep Testo personalizzato dell'evento", target_msg)

        mock_extract.assert_called_once_with(
            "Testo personalizzato dell'evento",
            b"collage_custom",
            self.context,
            "https://t.me/c/999/300",
            300,
            is_manual_trigger=True,
        )

    async def test_manual_trigger_fallback_when_not_in_cache(self):
        # The target message has a media_group_id that is NOT in the cache
        target_msg = self._album_photo("non_cached_album", 400, caption="Testo evento fallback",
                                       photo=telegram_photo(b"single_photo_fallback"), link="https://t.me/c/999/400")

        update, mock_extract = await self._ep("/ep", target_msg)

        mock_extract.assert_called_once_with(
            "Testo evento fallback",
            bytearray(b"single_photo_fallback"),
            self.context,
            "https://t.me/c/999/400",
            400,
            is_manual_trigger=True,
        )
        update.message.reply_text.assert_called_once_with("Processato il messaggio risposto.")

    async def test_manual_trigger_no_text_informs_user(self):
        target_msg = make_message(message_id=500, photo=[telegram_photo(b"photo")])

        update, mock_extract = await self._ep("/ep", target_msg)

        mock_extract.assert_not_called()
        update.message.reply_text.assert_called_once_with(
            "Nessun testo trovato nel messaggio o nel comando. Includi il testo o invia una didascalia."
        )


if __name__ == "__main__":
    unittest.main()
