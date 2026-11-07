import unittest
from unittest.mock import AsyncMock, patch

from telegram.error import BadRequest, TimedOut

from bot.common.media import PHOTO_UPLOAD_WRITE_TIMEOUT, send_photo_resilient
from bot.common.previews import send_admin_preview
from tests.support.config import patched_config
from tests.support.db import TempDBMixin
from tests.support.telegram import make_bot

R2_UPLOAD = {"id": "telegram-tmp/abc/photo.jpg", "source_url": "https://r2.example/telegram-tmp/abc/photo.jpg"}


class TestSendPhotoResilient(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.image_path = f"{self.temp_dir.name}/photo.jpg"
        with open(self.image_path, "wb") as f:
            f.write(b"IMAGE")
        for name, value in (("upload_media", R2_UPLOAD), ("delete_media", True), ("r2_configured", True)):
            patcher = patch(f"bot.common.media.{name}", return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.upload, self.delete = self.upload_media, self.delete_media
        via_r2 = patched_config(TELEGRAM_PHOTOS_VIA_R2=True)
        via_r2.__enter__()
        self.addCleanup(via_r2.__exit__, None, None, None)

    async def test_flag_off_uploads_directly_even_with_r2(self):
        send = AsyncMock(return_value="msg")
        with patched_config(TELEGRAM_PHOTOS_VIA_R2=False):
            self.assertEqual(await send_photo_resilient(send, self.image_path), "msg")
        send.assert_awaited_once_with(b"IMAGE", write_timeout=PHOTO_UPLOAD_WRITE_TIMEOUT, parse_mode="HTML")
        self.upload.assert_not_called()

    async def test_sends_r2_url_first_and_deletes_it(self):
        send = AsyncMock(return_value="msg")
        self.assertEqual(await send_photo_resilient(send, self.image_path), "msg")
        send.assert_awaited_once_with(R2_UPLOAD["source_url"], parse_mode="HTML")
        self.assertTrue(self.upload.call_args.args[1].startswith("telegram-tmp/"))
        self.delete.assert_called_once_with(R2_UPLOAD["id"])

    async def test_flag_on_without_r2_uploads_the_file(self):
        self.r2_configured.return_value = False
        send = AsyncMock(return_value="msg")
        self.assertEqual(await send_photo_resilient(send, self.image_path), "msg")
        send.assert_awaited_once_with(b"IMAGE", write_timeout=PHOTO_UPLOAD_WRITE_TIMEOUT, parse_mode="HTML")
        self.upload.assert_not_called()

    async def test_failed_r2_upload_falls_back_to_file_upload(self):
        self.upload.return_value = None
        send = AsyncMock(return_value="msg")
        await send_photo_resilient(send, self.image_path, html=False)
        send.assert_awaited_once_with(b"IMAGE", write_timeout=PHOTO_UPLOAD_WRITE_TIMEOUT)
        self.delete.assert_not_called()

    async def test_refused_url_falls_back_to_file_upload(self):
        send = AsyncMock(side_effect=[BadRequest("Wrong file identifier/http url specified"), "msg"])
        self.assertEqual(await send_photo_resilient(send, self.image_path, html=False), "msg")
        self.assertEqual(send.call_args_list[1].args, (b"IMAGE",))
        self.delete.assert_called_once_with(R2_UPLOAD["id"])

    async def test_timeout_on_url_send_is_raised_not_retried(self):
        send = AsyncMock(side_effect=TimedOut())
        with self.assertRaises(TimedOut):
            await send_photo_resilient(send, self.image_path)
        send.assert_awaited_once()
        self.delete.assert_called_once_with(R2_UPLOAD["id"])

    async def test_bad_markup_retries_plain_with_the_same_url(self):
        send = AsyncMock(side_effect=[BadRequest("Can't parse entities"), "msg"])
        self.assertEqual(await send_photo_resilient(send, self.image_path), "msg")
        self.assertEqual(send.call_args_list[1].args, (R2_UPLOAD["source_url"],))
        self.assertEqual(send.call_args_list[1].kwargs, {})

    async def test_admin_preview_falls_back_to_text_card(self):
        self.upload.return_value = None
        bot = make_bot()
        bot.send_photo.side_effect = TimedOut()
        with patched_config(ADMIN_CHAT_ID="1"):
            await send_admin_preview(bot, "testo", self.image_path, None)
        self.assertIn("Immagine non inviata", bot.send_message.call_args.kwargs["text"])
        self.assertTrue(bot.send_message.call_args.kwargs["text"].endswith("testo"))


if __name__ == "__main__":
    unittest.main()
