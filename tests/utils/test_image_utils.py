import io
import os
import tempfile
import unittest

from PIL import Image

from tests.support.images import image_bytes, image_file, make_image
from utils.image_utils import (
    MAX_PHOTO_DIMENSION_SUM,
    MAX_PHOTO_FILE_SIZE,
    MAX_PHOTO_SINGLE_DIMENSION,
    build_horizontal_collage,
    compress_existing_image_file,
    compress_image_to_bytes,
    create_collage,
    create_collage_from_bytes,
    move_image_locally,
    save_compressed_image,
)


class TempDirMixin:
    def setUp(self):
        super().setUp()
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.temp_dir = temp_dir.name


class TestImageCompression(TempDirMixin, unittest.TestCase):
    def test_compress_image_to_bytes_dimensions_enforcement(self):
        compressed_bytes = compress_image_to_bytes(make_image(6000, 5000))
        self.assertIsNotNone(compressed_bytes)

        res_img = Image.open(io.BytesIO(compressed_bytes))
        self.assertLessEqual(res_img.width + res_img.height, MAX_PHOTO_DIMENSION_SUM)
        self.assertLessEqual(max(res_img.width, res_img.height), MAX_PHOTO_SINGLE_DIMENSION)
        self.assertLessEqual(len(compressed_bytes), MAX_PHOTO_FILE_SIZE)

    def test_compress_image_to_bytes_target_size_enforcement(self):
        small_target = 50 * 1024
        compressed_bytes = compress_image_to_bytes(make_image(2000, 2000), target_max_bytes=small_target)
        self.assertIsNotNone(compressed_bytes)
        self.assertLessEqual(len(compressed_bytes), small_target)

    def test_save_compressed_image(self):
        out_path = os.path.join(self.temp_dir, "compressed.jpg")
        saved_path = save_compressed_image(make_image(5500, 4500), out_path)
        self.assertEqual(saved_path, out_path)
        self.assertTrue(os.path.exists(out_path))

        with Image.open(out_path) as im:
            self.assertLessEqual(im.width + im.height, MAX_PHOTO_DIMENSION_SUM)
            self.assertLessEqual(max(im.width, im.height), MAX_PHOTO_SINGLE_DIMENSION)
        self.assertLessEqual(os.path.getsize(out_path), MAX_PHOTO_FILE_SIZE)

    def test_compress_existing_image_file(self):
        img_path = image_file(self.temp_dir, "oversized.jpg", 6000, 5000)

        res_path = compress_existing_image_file(img_path, max_dim_sum=4000, max_single_dim=2500,
                                                target_max_bytes=100 * 1024)
        self.assertEqual(res_path, img_path)

        with Image.open(img_path) as im:
            self.assertLessEqual(im.width + im.height, 4000)
            self.assertLessEqual(max(im.width, im.height), 2500)
        self.assertLessEqual(os.path.getsize(img_path), 100 * 1024)

    def test_create_collage_compresses_and_enforces_dimensions(self):
        paths = [image_file(self.temp_dir, f"img_{i}.jpg", 3000, 2500, (i * 40, 50, 100)) for i in range(5)]
        collage_path = create_collage(paths, self.temp_dir, "07-10-2026")
        self.assertIsNotNone(collage_path)
        self.assertTrue(os.path.exists(collage_path))

        with Image.open(collage_path) as im:
            self.assertLessEqual(im.width + im.height, MAX_PHOTO_DIMENSION_SUM)
            self.assertLessEqual(max(im.width, im.height), MAX_PHOTO_SINGLE_DIMENSION)
        self.assertLessEqual(os.path.getsize(collage_path), MAX_PHOTO_FILE_SIZE)

    def test_create_collage_from_bytes_compresses(self):
        collage_bytes = create_collage_from_bytes([image_bytes(2500, 2000, (i * 50, 100, 150)) for i in range(4)])
        self.assertIsNotNone(collage_bytes)

        with Image.open(io.BytesIO(collage_bytes)) as im:
            self.assertLessEqual(im.width + im.height, MAX_PHOTO_DIMENSION_SUM)
            self.assertLessEqual(max(im.width, im.height), MAX_PHOTO_SINGLE_DIMENSION)
        self.assertLessEqual(len(collage_bytes), MAX_PHOTO_FILE_SIZE)


class TestCollage(unittest.TestCase):
    def test_build_horizontal_collage_proportions_and_dimensions(self):
        collage_bytes = create_collage_from_bytes([
            image_bytes(200, 300, (255, 0, 0)),  # aspect ratio 2/3
            image_bytes(400, 500, (0, 255, 0)),  # aspect ratio 4/5
            image_bytes(300, 400, (0, 0, 255)),  # aspect ratio 3/4
        ])
        self.assertIsNotNone(collage_bytes)

        collage_img = Image.open(io.BytesIO(collage_bytes))
        avg_height = int((300 + 500 + 400) / 3)  # 400
        self.assertEqual(collage_img.height, avg_height)

        expected_total_width = int(200 * (400 / 300)) + int(400 * (400 / 500)) + int(300 * (400 / 400))
        self.assertEqual(collage_img.width, expected_total_width)

    def test_build_collage_multi_row_wrap(self):
        images = [make_image(100, 100, color=(i * 20, i * 20, i * 20)) for i in range(5)]

        # Wrap at 2 per row -> 3 rows (2, 2, 1)
        collage = build_horizontal_collage(images, max_per_row=2)
        self.assertIsNotNone(collage)
        self.assertEqual(collage.height, 300)  # 3 rows of height 100
        self.assertEqual(collage.width, 200)  # widest row is 2 * 100

        # Wrap at 3 per row -> 2 rows (3, 2)
        collage = build_horizontal_collage(images, max_per_row=3)
        self.assertIsNotNone(collage)
        self.assertEqual(collage.height, 200)  # 2 rows of height 100
        self.assertEqual(collage.width, 300)  # widest row is 3 * 100

    def test_create_collage_from_bytes_single_and_empty(self):
        self.assertIsNone(create_collage_from_bytes([]))
        self.assertIsNone(create_collage_from_bytes(None))

        b1 = image_bytes(100, 100, (10, 20, 30))
        self.assertEqual(create_collage_from_bytes([b1]), b1)


class TestMoveImageLocally(TempDirMixin, unittest.TestCase):
    def test_move_image_locally(self):
        old_dir = os.path.join(self.temp_dir, "2026", "09", "08")
        os.makedirs(old_dir, exist_ok=True)
        img_path = os.path.join(old_dir, "test.jpg")
        with open(img_path, "w") as f:
            f.write("data")

        # Move to new date
        new_path = move_image_locally(img_path, self.temp_dir, "09-09-2026")
        expected_path = os.path.join(self.temp_dir, "2026", "09", "09", "test.jpg")
        self.assertEqual(new_path, expected_path)
        self.assertTrue(os.path.exists(expected_path))
        self.assertFalse(os.path.exists(img_path))
        # The old, now empty directory is cleaned up
        self.assertFalse(os.path.exists(old_dir))

        # Move same path -> noop
        self.assertEqual(move_image_locally(new_path, self.temp_dir, "09-09-2026"), expected_path)

        # Move non-existent file -> None
        self.assertIsNone(move_image_locally("/non/existent/file.jpg", self.temp_dir, "09-09-2026"))
        self.assertIsNone(move_image_locally(None, self.temp_dir, "09-09-2026"))


if __name__ == "__main__":
    unittest.main()
