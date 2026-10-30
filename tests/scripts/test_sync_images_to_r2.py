import os
import unittest
from unittest.mock import MagicMock, patch

from scripts import sync_images_to_r2 as script
from tests.support.config import patched_config
from tests.support.db import TempDBMixin, create_event
from tests.support.folders import FolderTestCase

DATE = "28-10-2026"
SLUG = "eventi-della-serata-mercoledi-28-10-2026"
BASE = "https://media.example.org"
PREFIX = f"serate/{SLUG}"
ARTICLE = (
    "---\n"
    f'cover: "{BASE}/{PREFIX}/collage_c1.jpg"\n'
    "tavoli:\n"
    f'  - {{ gioco: "Catan", tipo: tavolo, immagine: "{BASE}/{PREFIX}/event_a.jpg" }}\n'
    "---\n\n"
    f"![Catan]({BASE}/{PREFIX}/event_a.jpg)\n\n"
    f"![D&D]({BASE}/{PREFIX}/event_b.jpg)\n\n"
    "![Altro](https://other.example.org/serate/x/event_z.jpg)\n"
    f"![Un'altra serata]({BASE}/serate/altra/event_y.jpg)\n"
)


def _head(status):
    return MagicMock(status_code=status)


class TestPureHelpers(unittest.TestCase):
    def test_article_image_refs_collects_the_r2_images_once_each(self):
        refs = script.article_image_refs(ARTICLE, BASE + "/")

        self.assertEqual(refs, [
            (PREFIX, "collage_c1.jpg"), (PREFIX, "event_a.jpg"), (PREFIX, "event_b.jpg"), ("serate/altra", "event_y.jpg"),
        ])

    def test_other_hosts_are_ignored(self):
        self.assertEqual(script.article_image_refs("![x](https://other.example.org/serate/s/a.jpg)", BASE), [])


class TestRun(TempDBMixin, FolderTestCase):
    def setUp(self):
        TempDBMixin.setUp(self)
        FolderTestCase.setUp(self)
        self.config = dict(
            R2_PUBLIC_URL=BASE, R2_ACCOUNT_ID="a", R2_ACCESS_KEY_ID="k", R2_SECRET_ACCESS_KEY="s",
            ASTRO_GITHUB_REPO="o/r", ASTRO_GITHUB_TOKEN="t", DATA_DIR=self.data,
        )
        create_event(status="approved", title="Catan", normalized_date=DATE, image_path="data/2026/10/28/event_a.jpg")
        create_event(status="cancelled", title="D&D", normalized_date=DATE, image_path="data/2026/10/28/event_b.jpg")

    def run_script(self, *argv, article=ARTICLE, reachable_urls=(), upload_ok=True):
        """Runs the script; `reachable_urls` answer 200 before an upload, and every uploaded URL answers 200 afterwards."""
        uploaded = []

        def head(url, **kwargs):
            return _head(200 if url in reachable_urls or url in [f"{BASE}/{k}" for k in uploaded_keys()] else 404)

        def uploaded_keys():
            return [f"{prefix}/{os.path.basename(path)}" for prefix, path in uploaded]

        def upload(path, prefix):
            assert os.path.exists(path)
            uploaded.append((prefix, path))
            return {"id": "k", "source_url": "u"} if upload_ok else None

        with patched_config(**self.config), \
             patch("core.astro.storage.requests.head", side_effect=head), \
             patch("scripts.sync_images_to_r2.astro.published_article_text", return_value=article), \
             patch("scripts.sync_images_to_r2.astro.upload_media", side_effect=upload) as upload_mock:
            code = script.run(script.parse_args(list(argv)))
        return code, uploaded, upload_mock

    def test_loose_and_zipped_files_are_uploaded_under_the_articles_own_keys(self):
        self.write("collage_c1.jpg")
        self.write("event_a.jpg")
        self.zip({"event_b.jpg": b"zipped"})
        zip_before = os.listdir(self.day)

        code, uploaded, _ = self.run_script(DATE, "--article-file", self._article_file(ARTICLE.replace(f"![Un'altra serata]({BASE}/serate/altra/event_y.jpg)\n", "")))

        self.assertEqual(code, 0)
        self.assertEqual(sorted((prefix, os.path.basename(path)) for prefix, path in uploaded),
                         [(PREFIX, "collage_c1.jpg"), (PREFIX, "event_a.jpg"), (PREFIX, "event_b.jpg")])
        self.assertEqual(os.listdir(self.day), zip_before)  # nothing extracted into data/
        zipped = [path for _prefix, path in uploaded if path.endswith("event_b.jpg")][0]
        self.assertFalse(os.path.exists(zipped))  # the temporary copy is gone

    def _article_file(self, text):
        path = os.path.join(self.tmp.name, "article.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_reachable_images_are_skipped_unless_forced(self):
        for name in ("collage_c1.jpg", "event_a.jpg", "event_b.jpg"):
            self.write(name)
        urls = [f"{BASE}/{PREFIX}/{n}" for n in ("collage_c1.jpg", "event_a.jpg", "event_b.jpg")] + [f"{BASE}/serate/altra/event_y.jpg"]

        code, uploaded, _ = self.run_script(DATE, reachable_urls=urls)
        self.assertEqual((code, uploaded), (0, []))

        code, uploaded, _ = self.run_script(DATE, "--force", reachable_urls=urls)
        self.assertEqual(len(uploaded), 3)  # the ones found locally; "altra/event_y.jpg" is not on disk
        self.assertEqual(code, 1)

    def test_a_file_missing_locally_is_reported_and_the_others_still_upload(self):
        self.write("event_a.jpg")

        code, uploaded, _ = self.run_script(DATE)

        self.assertEqual(code, 1)
        self.assertEqual([os.path.basename(path) for _p, path in uploaded], ["event_a.jpg"])

    def test_an_upload_that_stays_unreachable_is_a_problem(self):
        self.write("event_a.jpg")
        article = f"![x]({BASE}/{PREFIX}/event_a.jpg)"

        with patched_config(**self.config), \
             patch("core.astro.storage.requests.head", return_value=_head(404)), \
             patch("scripts.sync_images_to_r2.astro.published_article_text", return_value=article), \
             patch("scripts.sync_images_to_r2.astro.upload_media", return_value={"id": "k", "source_url": "u"}):
            code = script.run(script.parse_args([DATE]))

        self.assertEqual(code, 1)

    def test_a_failed_upload_is_a_problem(self):
        self.write("event_a.jpg")

        code, _uploaded, _ = self.run_script(DATE, "--article-file", self._article_file(f"![x]({BASE}/{PREFIX}/event_a.jpg)"), upload_ok=False)

        self.assertEqual(code, 1)

    def test_dry_run_uploads_nothing(self):
        self.write("event_a.jpg")
        self.write("collage_c1.jpg")

        code, uploaded, upload_mock = self.run_script(DATE, "--dry-run")

        upload_mock.assert_not_called()
        self.assertEqual(uploaded, [])
        self.assertEqual(code, 1)  # event_b.jpg and the other night's image are not on disk

    def test_all_uses_the_event_images_and_every_collage_under_the_nights_prefix(self):
        self.write("event_a.jpg")
        self.write("event_b.jpg")
        self.write("collage_c1.jpg")
        self.write("collage_c2.jpg")
        self.write("story_1.jpg")

        code, uploaded, _ = self.run_script(DATE, "--all", article=None)

        self.assertEqual(code, 0)
        self.assertEqual(sorted((prefix, os.path.basename(path)) for prefix, path in uploaded),
                         [(PREFIX, "collage_c1.jpg"), (PREFIX, "collage_c2.jpg"), (PREFIX, "event_a.jpg"), (PREFIX, "event_b.jpg")])

    def test_article_that_cannot_be_read_points_to_the_alternatives(self):
        for article in (None, "senza immagini"):
            with self.subTest(article=article), patch("builtins.print") as printed:
                code, uploaded, _ = self.run_script(DATE, article=article)
            self.assertEqual((code, uploaded), (1, []))
            self.assertIn("--article-file", printed.call_args_list[-1].args[0])
            self.assertIn("--all", printed.call_args_list[-1].args[0])

    def test_invalid_date_and_missing_settings_are_refused(self):
        self.assertEqual(self.run_script("2026-10-28")[0], 1)
        with patched_config(**{**self.config, "R2_SECRET_ACCESS_KEY": None}):
            self.assertEqual(script.missing_settings(script.parse_args([DATE, "--all"])), ["R2_SECRET_ACCESS_KEY"])
            self.assertEqual(script.missing_settings(script.parse_args([DATE, "--all", "--dry-run"])), [])
        with patched_config(**{**self.config, "ASTRO_GITHUB_TOKEN": None}):
            self.assertEqual(script.missing_settings(script.parse_args([DATE])), ["ASTRO_GITHUB_TOKEN"])
            self.assertEqual(script.missing_settings(script.parse_args([DATE, "--all"])), [])

    def test_all_and_article_file_cannot_be_combined(self):
        with self.assertRaises(SystemExit):
            script.parse_args([DATE, "--all", "--article-file", "x.md"])


if __name__ == "__main__":
    unittest.main()
