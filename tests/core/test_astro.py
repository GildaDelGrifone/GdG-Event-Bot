import base64
import io
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image

from core import astro
from core.astro import content, github, storage
from tests.support.config import patched_config
from tests.support.images import image_file, make_image

R2 = dict(R2_ACCOUNT_ID="acc", R2_ACCESS_KEY_ID="k", R2_SECRET_ACCESS_KEY="s", R2_BUCKET="gdg-media",
          R2_PUBLIC_URL="https://pub.r2.dev")
GH = dict(ASTRO_GITHUB_REPO="o/r", ASTRO_GITHUB_BRANCH="main", ASTRO_GITHUB_TOKEN="tok",
          ASTRO_CONTENT_DIR="src/content/serate", ASTRO_BASE_URL="https://example.org")


def _response(status, body=None, text=""):
    resp = MagicMock(status_code=status, text=text)
    resp.json.return_value = body or {}
    return resp


class TestUpload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def upload(self, path, client):
        with patched_config(**R2), patch("core.astro.storage.r2_client", return_value=client):
            return storage.upload_media(path, "serate/slug/")

    def test_key_url_and_content_type(self):
        client = MagicMock()
        path = image_file(self.tmp.name, "catan.jpg", 400, 300)

        result = self.upload(path, client)

        self.assertEqual(result, {"id": "serate/slug/catan.jpg", "source_url": "https://pub.r2.dev/serate/slug/catan.jpg"})
        kwargs = client.put_object.call_args.kwargs
        self.assertEqual((kwargs["Bucket"], kwargs["Key"], kwargs["ContentType"]), ("gdg-media", "serate/slug/catan.jpg", "image/jpeg"))

    def test_wide_images_are_resized_to_1600(self):
        client = MagicMock()
        self.upload(image_file(self.tmp.name, "wide.jpg", 3200, 2000), client)

        sent = Image.open(io.BytesIO(client.put_object.call_args.kwargs["Body"]))
        self.assertEqual(sent.size, (1600, 1000))

    def test_small_images_keep_their_size(self):
        client = MagicMock()
        self.upload(image_file(self.tmp.name, "small.jpg", 800, 600), client)

        sent = Image.open(io.BytesIO(client.put_object.call_args.kwargs["Body"]))
        self.assertEqual(sent.size, (800, 600))

    def test_exif_orientation_is_applied(self):
        client = MagicMock()
        path = os.path.join(self.tmp.name, "rot.jpg")
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 90 degrees clockwise to display
        make_image(400, 200).save(path, format="JPEG", exif=exif)

        self.upload(path, client)

        sent = Image.open(io.BytesIO(client.put_object.call_args.kwargs["Body"]))
        self.assertEqual(sent.size, (200, 400))

    def test_png_stays_png(self):
        client = MagicMock()
        path = os.path.join(self.tmp.name, "a.png")
        make_image(100, 100).save(path, format="PNG")

        self.upload(path, client)

        self.assertEqual(client.put_object.call_args.kwargs["ContentType"], "image/png")
        self.assertEqual(Image.open(io.BytesIO(client.put_object.call_args.kwargs["Body"])).format, "PNG")

    def test_missing_configuration_or_failure_returns_none(self):
        path = image_file(self.tmp.name, "a.jpg", 10, 10)
        self.assertIsNone(self.upload(path, None))
        client = MagicMock()
        client.put_object.side_effect = Exception("denied")
        self.assertIsNone(self.upload(path, client))


    def test_missing_boto3_returns_none_instead_of_raising(self):
        path = image_file(self.tmp.name, "a.jpg", 10, 10)
        with patched_config(**R2), patch("core.astro.storage.r2_client", side_effect=ImportError("boto3")), \
             self.assertLogs("core.astro.storage", level="ERROR") as logs:
            self.assertIsNone(storage.upload_media(path, "serate/slug"))
        self.assertIn("boto3 is not installed", logs.output[0])


class TestRealR2Client(unittest.TestCase):
    def test_client_uses_the_r2_endpoint_and_requires_all_settings(self):
        from core.astro.client import r2_client

        with patched_config(**R2), patch("boto3.client") as boto_client:
            r2_client()
        kwargs = boto_client.call_args.kwargs
        self.assertEqual(kwargs["endpoint_url"], "https://acc.r2.cloudflarestorage.com")
        self.assertEqual(kwargs["region_name"], "auto")
        with patched_config(**{**R2, "R2_SECRET_ACCESS_KEY": None}):
            self.assertIsNone(r2_client())


class TestContent(unittest.TestCase):
    def test_slug_strips_accents_from_the_weekday(self):
        self.assertEqual(content.article_slug("23-10-2026"), "eventi-della-serata-venerdi-23-10-2026")
        self.assertEqual(content.article_slug("21-10-2026"), "eventi-della-serata-mercoledi-21-10-2026")

    def test_public_url(self):
        with patched_config(**GH):
            self.assertEqual(
                astro.public_url("23-10-2026", "eventi-della-serata-venerdi-23-10-2026"),
                "https://example.org/serate/2026-10-23-eventi-della-serata-venerdi-23-10-2026/",
            )

    def test_front_matter_matches_the_site_schema(self):
        text = astro.build_front_matter(
            "Eventi della Serata: Venerdì 23-10-2026", "2026-10-23", "https://r2/c.jpg", "Un estratto…",
            [{"gioco": "Catan", "tipo": "tavolo", "immagine": "https://r2/catan.jpg"}, {"gioco": "D&D", "tipo": "gdr"}],
        )
        self.assertEqual(text, (
            '---\n'
            'title: "Eventi della Serata: Venerdì 23-10-2026"\n'
            'date: 2026-10-23\n'
            'cover: "https://r2/c.jpg"\n'
            'excerpt: "Un estratto…"\n'
            'tavoli:\n'
            '  - { gioco: "Catan", tipo: tavolo, immagine: "https://r2/catan.jpg" }\n'
            '  - { gioco: "D&D", tipo: gdr }\n'
            '---\n'
        ))

    def test_front_matter_escapes_quotes_and_omits_empty_fields(self):
        text = astro.build_front_matter('Il "gioco": a\\b', "2026-10-23", None, 'Dice "ciao"', [])
        self.assertIn('title: "Il \\"gioco\\": a\\\\b"', text)
        self.assertIn('excerpt: "Dice \\"ciao\\""', text)
        self.assertNotIn("cover", text)
        self.assertNotIn("tavoli", text)

    def test_excerpt_is_plain_text_cut_with_ellipsis(self):
        body = "### Titolo\n\n![x](https://r2/x.jpg)\n\nUna **serata** con [Catan](https://t.me/x) " + "parola " * 60
        excerpt = content.make_excerpt(body)
        self.assertTrue(excerpt.startswith("Titolo Una serata con Catan parola"))
        self.assertTrue(excerpt.endswith("…"))
        self.assertLessEqual(len(excerpt), 161)
        self.assertEqual(content.make_excerpt("Breve testo"), "Breve testo")


class TestGithub(unittest.TestCase):
    def run_publish(self, responses):
        with patched_config(**GH), patch("core.astro.client.requests.request", side_effect=responses) as req:
            result = astro.publish_article(
                "Titolo", "Corpo", "23-10-2026", "eventi-della-serata-venerdi-23-10-2026", "https://r2/c.jpg", "Estratto",
                [{"gioco": "Catan", "tipo": "tavolo"}],
            )
        return result, req

    def test_draft_creates_branch_and_commits_the_file(self):
        result, req = self.run_publish([
            _response(200, {"object": {"sha": "abc"}}),
            _response(201),
            _response(404),
            _response(201),
        ])

        branch = "serata/eventi-della-serata-venerdi-23-10-2026"
        path = "src/content/serate/2026-10-23-eventi-della-serata-venerdi-23-10-2026.md"
        self.assertEqual(result, (f"https://github.com/o/r/blob/{branch}/{path}", branch))
        calls = [(c.args[0], c.args[1]) for c in req.call_args_list]
        self.assertEqual(calls, [
            ("GET", "https://api.github.com/repos/o/r/git/ref/heads/main"),
            ("POST", "https://api.github.com/repos/o/r/git/refs"),
            ("GET", f"https://api.github.com/repos/o/r/contents/{path}"),
            ("PUT", f"https://api.github.com/repos/o/r/contents/{path}"),
        ])
        self.assertEqual(req.call_args_list[1].kwargs["json"], {"ref": f"refs/heads/{branch}", "sha": "abc"})
        put = req.call_args_list[3].kwargs
        self.assertEqual(put["json"]["branch"], branch)
        committed = base64.b64decode(put["json"]["content"]).decode()
        self.assertTrue(committed.startswith('---\ntitle: "Titolo"\ndate: 2026-10-23\n'))
        self.assertTrue(committed.endswith("---\n\nCorpo\n"))
        self.assertEqual(req.call_args_list[0].kwargs["headers"]["Authorization"], "Bearer tok")

    def test_existing_branch_and_file_are_reused_and_updated(self):
        result, req = self.run_publish([
            _response(200, {"object": {"sha": "abc"}}),
            _response(422, text="Reference already exists"),
            _response(200, {"sha": "old"}),
            _response(200),
        ])

        self.assertTrue(result[0])
        self.assertEqual(req.call_args_list[3].kwargs["json"]["sha"], "old")

    def test_failures_return_false_none(self):
        for name, responses in {
            "no main branch": [_response(404)],
            "branch refused": [_response(200, {"object": {"sha": "a"}}), _response(403, text="no")],
            "commit refused": [_response(200, {"object": {"sha": "a"}}), _response(201), _response(404), _response(422)],
            "network error": [Exception("down")],
        }.items():
            with self.subTest(name):
                result, _ = self.run_publish(responses)
                self.assertEqual(result, (False, None))

    def test_missing_token_returns_false_none_without_network(self):
        with patched_config(**{**GH, "ASTRO_GITHUB_TOKEN": None}), patch("core.astro.client.requests.request") as req:
            self.assertEqual(astro.publish_article("T", "B", "23-10-2026", "s", None, "e", []), (False, None))
            self.assertFalse(astro.update_article_status("serata/s"))
        req.assert_not_called()

    def test_publish_merges_then_deletes_the_branch(self):
        for merge_status in (201, 204):
            with self.subTest(merge_status=merge_status), patched_config(**GH), \
                 patch("core.astro.client.requests.request", side_effect=[_response(merge_status), _response(204)]) as req:
                self.assertTrue(astro.update_article_status("serata/s", "publish"))
            self.assertEqual(req.call_args_list[0].kwargs["json"],
                             {"base": "main", "head": "serata/s", "commit_message": "Pubblica serata/s"})
            self.assertEqual((req.call_args_list[1].args[0], req.call_args_list[1].args[1]),
                             ("DELETE", "https://api.github.com/repos/o/r/git/refs/heads/serata/s"))

    def test_merge_conflict_fails_and_keeps_the_branch(self):
        with patched_config(**GH), patch("core.astro.client.requests.request", return_value=_response(409, text="conflict")) as req:
            self.assertFalse(astro.update_article_status("serata/s", "publish"))
        self.assertEqual(req.call_count, 1)

    def test_failed_branch_delete_still_counts_as_published(self):
        with patched_config(**GH), patch("core.astro.client.requests.request", side_effect=[_response(201), _response(422)]):
            self.assertTrue(astro.update_article_status("serata/s", "publish"))

    def test_other_statuses_are_refused(self):
        with patched_config(**GH), patch("core.astro.client.requests.request") as req:
            self.assertFalse(astro.update_article_status("serata/s", "draft"))
        req.assert_not_called()

    def test_github_helpers_are_importable(self):
        self.assertTrue(callable(github.merge_branch) and callable(github.delete_branch))


class TestDiscardArticle(unittest.TestCase):
    def discard(self, responses):
        with patched_config(**GH), patch("core.astro.client.requests.request", side_effect=responses) as req:
            return astro.discard_article("serata/s"), req

    def test_existing_branch_is_deleted(self):
        result, req = self.discard([_response(200, {"object": {"sha": "abc"}}), _response(204)])

        self.assertIs(result, True)
        self.assertEqual([(c.args[0], c.args[1]) for c in req.call_args_list], [
            ("GET", "https://api.github.com/repos/o/r/git/ref/heads/serata/s"),
            ("DELETE", "https://api.github.com/repos/o/r/git/refs/heads/serata/s"),
        ])

    def test_missing_branch_means_already_published(self):
        result, req = self.discard([_response(404)])

        self.assertEqual(result, "published")
        self.assertEqual(req.call_count, 1)

    def test_failures_return_false(self):
        self.assertIs(self.discard([_response(200, {"object": {"sha": "a"}}), _response(422)])[0], False)
        self.assertIs(self.discard([Exception("down")])[0], False)
        with patched_config(**{**GH, "ASTRO_GITHUB_TOKEN": None}):
            self.assertIs(astro.discard_article("serata/s"), False)

if __name__ == "__main__":
    unittest.main()
