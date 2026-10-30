import datetime
import os
import unittest

from tests.support.config import patched_config
from tests.support.folders import FolderTestCase
from utils import night_images


class TestNightImages(FolderTestCase):
    def test_loose_file_wins_over_the_archive(self):
        loose = self.write("event_a.jpg")
        self.zip({"event_a.jpg": b"zipped"})

        self.assertEqual(night_images.find_local_file("event_a.jpg", [self.day]), (loose, None))

    def test_file_inside_the_archive(self):
        archive = self.zip({"event_a.jpg": b"zipped"})

        self.assertEqual(night_images.find_local_file("event_a.jpg", [self.day]), (archive, "event_a.jpg"))
        self.assertIsNone(night_images.find_local_file("missing.jpg", [self.day]))

    def test_extract_member_writes_the_bytes_to_the_target_dir(self):
        archive = self.zip({"sub/event_a.jpg": b"zipped"})
        target = os.path.join(self.tmp.name, "out")
        os.makedirs(target)

        path = night_images.extract_member(archive, "sub/event_a.jpg", target)

        self.assertEqual(path, os.path.join(target, "event_a.jpg"))
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"zipped")

    def test_candidate_folders_rebase_relative_data_paths_onto_data_dir(self):
        with patched_config(DATA_DIR="/var/gdg"):
            folders = night_images.candidate_folders(
                datetime.datetime(2026, 10, 28), [{"image_path": "data/2026/10/28/event_a.jpg"}, {"image_path": None}])

        self.assertEqual(folders, ["data/2026/10/28", "/var/gdg/2026/10/28"])

    def _set_mtime(self, path, seconds):
        os.utime(path, (seconds, seconds))

    def test_newest_collage_is_the_most_recently_modified_loose_one(self):
        old = self.write("collage_old.jpg")
        new = self.write("collage_new.jpg")
        self.write("event_a.jpg")
        self._set_mtime(old, 1_000_000)
        self._set_mtime(new, 2_000_000)

        self.assertEqual(night_images.newest_collage([self.day]), "collage_new.jpg")

    def test_a_zipped_collage_can_be_the_newest(self):
        loose = self.write("collage_loose.jpg")
        self._set_mtime(loose, 1_000_000)
        self.zip({"collage_zipped.jpg": b"z", "event_a.jpg": b"e"})

        self.assertEqual(night_images.newest_collage([self.day]), "collage_zipped.jpg")

    def test_a_loose_collage_newer_than_the_archive_wins(self):
        self.zip({"collage_zipped.jpg": b"z"})
        loose = self.write("collage_loose.jpg")
        self._set_mtime(loose, datetime.datetime.now().timestamp() + 3600)

        self.assertEqual(night_images.newest_collage([self.day]), "collage_loose.jpg")

    def test_no_collage_gives_none_and_other_files_are_ignored(self):
        self.write("event_a.jpg")
        self.zip({"event_b.jpg": b"e"})

        self.assertIsNone(night_images.newest_collage([self.day]))
        self.assertEqual(night_images.collage_names([self.day]), [])

    def test_collage_names_lists_loose_and_zipped_ones_once(self):
        self.write("collage_a.jpg")
        self.zip({"collage_a.jpg": b"1", "collage_b.jpg": b"2"})

        self.assertEqual(sorted(night_images.collage_names([self.day])), ["collage_a.jpg", "collage_b.jpg"])


if __name__ == "__main__":
    unittest.main()
