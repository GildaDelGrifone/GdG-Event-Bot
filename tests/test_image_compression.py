import io
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image

from utils.image_utils import (
    compress_image_to_bytes,
    save_compressed_image,
    compress_existing_image_file,
    create_collage,
    create_collage_from_bytes,
    MAX_PHOTO_DIMENSION_SUM,
    MAX_PHOTO_SINGLE_DIMENSION,
    MAX_PHOTO_FILE_SIZE,
)


class TestImageCompression(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_dummy_image(self, width, height, color=(100, 150, 200)):
        return Image.new("RGB", (width, height), color=color)

    def _create_dummy_image_file(self, filename, width, height, color=(100, 150, 200)):
        img = self._create_dummy_image(width, height, color)
        path = os.path.join(self.temp_dir.name, filename)
        img.save(path, format="JPEG", quality=95)
        return path

    def test_compress_image_to_bytes_dimensions_enforcement(self):
        huge_img = self._create_dummy_image(6000, 5000)
        compressed_bytes = compress_image_to_bytes(huge_img)
        self.assertIsNotNone(compressed_bytes)

        res_img = Image.open(io.BytesIO(compressed_bytes))
        dim_sum = res_img.width + res_img.height
        self.assertLessEqual(dim_sum, MAX_PHOTO_DIMENSION_SUM)
        self.assertLessEqual(max(res_img.width, res_img.height), MAX_PHOTO_SINGLE_DIMENSION)
        self.assertLessEqual(len(compressed_bytes), MAX_PHOTO_FILE_SIZE)

    def test_compress_image_to_bytes_target_size_enforcement(self):
        img = self._create_dummy_image(2000, 2000)
        small_target = 50 * 1024
        compressed_bytes = compress_image_to_bytes(img, target_max_bytes=small_target)
        self.assertIsNotNone(compressed_bytes)
        self.assertLessEqual(len(compressed_bytes), small_target)

    def test_save_compressed_image(self):
        huge_img = self._create_dummy_image(5500, 4500)
        out_path = os.path.join(self.temp_dir.name, "compressed.jpg")
        saved_path = save_compressed_image(huge_img, out_path)
        self.assertEqual(saved_path, out_path)
        self.assertTrue(os.path.exists(out_path))

        with Image.open(out_path) as im:
            self.assertLessEqual(im.width + im.height, MAX_PHOTO_DIMENSION_SUM)
            self.assertLessEqual(max(im.width, im.height), MAX_PHOTO_SINGLE_DIMENSION)
        self.assertLessEqual(os.path.getsize(out_path), MAX_PHOTO_FILE_SIZE)

    def test_compress_existing_image_file(self):
        img_path = self._create_dummy_image_file("oversized.jpg", 6000, 5000)

        res_path = compress_existing_image_file(
            img_path,
            max_dim_sum=4000,
            max_single_dim=2500,
            target_max_bytes=100 * 1024
        )
        self.assertEqual(res_path, img_path)

        with Image.open(img_path) as im:
            self.assertLessEqual(im.width + im.height, 4000)
            self.assertLessEqual(max(im.width, im.height), 2500)
        self.assertLessEqual(os.path.getsize(img_path), 100 * 1024)

    def test_create_collage_compresses_and_enforces_dimensions(self):
        paths = [
            self._create_dummy_image_file(f"img_{i}.jpg", 3000, 2500, (i * 40, 50, 100))
            for i in range(5)
        ]
        collage_path = create_collage(paths, self.temp_dir.name, "07-10-2026")
        self.assertIsNotNone(collage_path)
        self.assertTrue(os.path.exists(collage_path))

        with Image.open(collage_path) as im:
            self.assertLessEqual(im.width + im.height, MAX_PHOTO_DIMENSION_SUM)
            self.assertLessEqual(max(im.width, im.height), MAX_PHOTO_SINGLE_DIMENSION)
        self.assertLessEqual(os.path.getsize(collage_path), MAX_PHOTO_FILE_SIZE)

    def test_create_collage_from_bytes_compresses(self):
        img_bytes_list = []
        for i in range(4):
            img = self._create_dummy_image(2500, 2000, (i * 50, 100, 150))
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            img_bytes_list.append(buf.getvalue())

        collage_bytes = create_collage_from_bytes(img_bytes_list)
        self.assertIsNotNone(collage_bytes)

        with Image.open(io.BytesIO(collage_bytes)) as im:
            self.assertLessEqual(im.width + im.height, MAX_PHOTO_DIMENSION_SUM)
            self.assertLessEqual(max(im.width, im.height), MAX_PHOTO_SINGLE_DIMENSION)
        self.assertLessEqual(len(collage_bytes), MAX_PHOTO_FILE_SIZE)

    async def test_scheduler_emergency_recompression_on_photo_invalid_dimensions(self):
        from core.scheduler.recap import generate_daily_recap

        mock_bot = MagicMock()
        mock_bot.send_photo = AsyncMock(side_effect=[
            Exception("Bad Request: Photo_invalid_dimensions"),
            MagicMock(message_id=999)
        ])
        mock_bot.send_message = AsyncMock()

        dummy_event = {
            "id": 101,
            "title": "Big Event",
            "system": "D&D",
            "status": "approved",
            "normalized_date": "07-10-2026",
            "booked_seats": 2,
            "max_seats": 5,
            "image_path": self._create_dummy_image_file("event.jpg", 1000, 1000)
        }

        with patch("core.scheduler.recap.get_pending_events_for_recap", return_value=[dummy_event]), \
             patch("core.scheduler.recap.mark_events_as_recap"):

            res = await generate_daily_recap(mock_bot, manual_date="07-10-2026", is_manual=True)
            self.assertTrue(res)

            self.assertEqual(mock_bot.send_photo.call_count, 2)
            mock_bot.send_message.assert_not_called()
