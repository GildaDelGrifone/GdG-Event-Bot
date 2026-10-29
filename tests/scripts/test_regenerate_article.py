import base64
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import requests

from scripts import regenerate_article as script
from tests.support.config import patched_config
from tests.support.db import TempDBMixin, create_event

DATE = "28-10-2026"
SLUG = "eventi-della-serata-mercoledi-28-10-2026"
CONFIG = dict(
    GEMINI_API_KEY="key", R2_PUBLIC_URL="https://media.example.org", ASTRO_GITHUB_REPO="o/r",
    ASTRO_GITHUB_TOKEN="tok", ASTRO_GITHUB_BRANCH="main", ASTRO_CONTENT_DIR="src/content/serate",
    ASTRO_BASE_URL="https://example.org",
)
GOOD_ARTICLE = (
    "Ciao a tutti! La **Gilda del Grifone** vi aspetta **mercoledì 28-10-2026**.\n\n"
    "Ecco cosa bolle in pentola per stasera:\n\n"
    "### Catan (Board Game)\n\nTavolo aperto.\n\n![Catan](https://media.example.org/x.jpg)\n\n[Prenotati qui](https://t.me/G/1)\n\n"
    "### D&D (D&D 5e)\n\nTavolo **annullato**.\n\n[Dettagli](https://t.me/G/2)\n\n"
    "---\n\n**Tutto pieno?** Vieni lo stesso: **@Destard** ([https://t.me/Destard](https://t.me/Destard)).\n\n"
    "Vi aspettiamo in sede alle **20:45**! 🦅"
)


def _head(status=200):
    return MagicMock(status_code=status)


class TestCheckStructure(unittest.TestCase):
    EVENTS = [{"id": 1}, {"id": 2}]

    def test_a_correct_article_has_no_problems(self):
        self.assertEqual(script.check_structure(GOOD_ARTICLE, self.EVENTS), [])

    def test_plain_contact_addresses_are_accepted_but_plain_event_links_are_not(self):
        contacts = "contatta **@Destard** (https://t.me/Destard) o **@ManueleAbi** (https://t.me/ManueleAbi)"
        body = GOOD_ARTICLE.replace("**@Destard** ([https://t.me/Destard](https://t.me/Destard))", contacts)

        with patched_config(RECAP_CONTACTS=["@Destard", "@ManueleAbi"]):
            self.assertEqual(script.check_structure(body, self.EVENTS), [])
            plain_event = body.replace("[Prenotati qui](https://t.me/G/1)", "https://t.me/G/1")
            self.assertEqual(len(script.check_structure(plain_event, self.EVENTS)), 1)

    def test_each_deviation_is_reported(self):
        body = "### Titolo\n\nTesto https://t.me/G/1\n\n### Uno\n\n### Due\n\n### Tre\n"

        problems = script.check_structure(body, self.EVENTS)

        self.assertEqual(len(problems), 4)
        self.assertTrue(any("titolo" in p for p in problems))
        self.assertTrue(any("4 sezioni" in p for p in problems))
        self.assertTrue(any("---" in p for p in problems))
        self.assertTrue(any("senza link" in p for p in problems))


class TestImageUrls(unittest.TestCase):
    def test_url_comes_from_the_file_name_and_unreachable_images_are_dropped(self):
        events = [
            {"image_path": "/data/2026/10/28/event_a.jpg"},
            {"image_path": "data/2026/10/28/event_b.jpg"},
            {"image_path": None},
        ]
        with patched_config(**CONFIG), patch("scripts.regenerate_article.requests.head",
                                             side_effect=[_head(200), _head(404)]) as head:
            script.attach_image_urls(events, SLUG)

        self.assertEqual(events[0]["media_url"], f"https://media.example.org/serate/{SLUG}/event_a.jpg")
        self.assertNotIn("media_url", events[1])
        self.assertNotIn("media_url", events[2])
        self.assertEqual(head.call_count, 2)

    def test_a_network_error_counts_as_unreachable(self):
        events = [{"image_path": "/x/event_a.jpg"}]
        with patched_config(**CONFIG), patch("scripts.regenerate_article.requests.head",
                                             side_effect=requests.ConnectionError("down")):
            script.attach_image_urls(events, SLUG)

        self.assertNotIn("media_url", events[0])


class TestExistingCover(unittest.TestCase):
    def _response(self, status, text=""):
        response = MagicMock(status_code=status)
        response.json.return_value = {"content": base64.b64encode(text.encode()).decode()}
        return response

    def test_cover_is_read_from_the_front_matter_of_the_existing_article(self):
        text = '---\ntitle: "T"\ncover: "https://media.example.org/collage.jpg"\nexcerpt: "e"\n---\n'
        with patched_config(**CONFIG), patch("scripts.regenerate_article.gh_request",
                                             return_value=self._response(200, text)) as gh:
            cover = script.existing_cover(DATE, SLUG)

        self.assertEqual(cover, "https://media.example.org/collage.jpg")
        self.assertEqual(gh.call_args.args[1], f"contents/src/content/serate/2026-10-28-{SLUG}.md")
        self.assertEqual(gh.call_args.kwargs["params"], {"ref": "main"})

    def test_missing_article_or_cover_gives_none(self):
        with patched_config(**CONFIG):
            with patch("scripts.regenerate_article.gh_request", return_value=self._response(404)):
                self.assertIsNone(script.existing_cover(DATE, SLUG))
            with patch("scripts.regenerate_article.gh_request", return_value=self._response(200, "---\ntitle: T\n---\n")):
                self.assertIsNone(script.existing_cover(DATE, SLUG))
            with patch("scripts.regenerate_article.gh_request", side_effect=RuntimeError("no credentials")):
                self.assertIsNone(script.existing_cover(DATE, SLUG))


class TestRun(TempDBMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.catan = create_event(status="approved", title="Catan", normalized_date=DATE, date=DATE, is_roleplay=0,
                                  message_link="https://t.me/G/1", image_path="/data/2026/10/28/event_a.jpg")
        self.dnd = create_event(status="cancelled", title="D&D", normalized_date=DATE, date=DATE, is_roleplay=1,
                                message_link="https://t.me/G/2", image_path=None)

    def run_script(self, *argv, articles=(GOOD_ARTICLE,), cover="https://media.example.org/collage.jpg"):
        args = script.parse_args(list(argv))
        with patched_config(**CONFIG), \
             patch("scripts.regenerate_article.requests.head", return_value=_head(200)), \
             patch("scripts.regenerate_article.existing_cover", return_value=cover), \
             patch("scripts.regenerate_article.generate_astro_article", side_effect=list(articles)) as gen, \
             patch("scripts.regenerate_article.astro.publish_article",
                   return_value=("https://github.com/o/r/blob/b/f.md", f"serata/{SLUG}")) as publish, \
             patch("scripts.regenerate_article.astro.update_article_status", return_value=True) as merge:
            code = script.run(args)
        return code, gen, publish, merge

    def test_default_creates_only_the_draft_with_the_reused_image_and_cover(self):
        code, gen, publish, merge = self.run_script(DATE)

        self.assertEqual(code, 0)
        publish.assert_called_once()
        title, body, date_str, slug, cover, excerpt, tavoli = publish.call_args.args
        self.assertEqual((title, date_str, slug), ("Eventi della Serata: Mercoledì 28-10-2026", DATE, SLUG))
        self.assertEqual(cover, "https://media.example.org/collage.jpg")
        self.assertEqual(tavoli, [{
            "gioco": "Catan", "tipo": "tavolo", "link": "https://t.me/G/1",
            "immagine": f"https://media.example.org/serate/{SLUG}/event_a.jpg",
        }])
        merge.assert_not_called()
        events_sent = gen.call_args.args[1]
        self.assertEqual([ev["title"] for ev in events_sent], ["Catan", "D&D"])

    def test_publish_merges_the_draft_branch(self):
        code, _gen, _publish, merge = self.run_script(DATE, "--publish")

        self.assertEqual(code, 0)
        merge.assert_called_once_with(f"serata/{SLUG}", "publish")

    def test_dry_run_writes_the_file_and_never_touches_github(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "a.md")
            code, _gen, publish, merge = self.run_script(DATE, "--dry-run", "--output", out)
            with open(out, encoding="utf-8") as f:
                text = f.read()

        self.assertEqual(code, 0)
        publish.assert_not_called()
        merge.assert_not_called()
        self.assertTrue(text.startswith('---\ntitle: "Eventi della Serata: Mercoledì 28-10-2026"\ndate: 2026-10-28\n'))
        self.assertIn('link: "https://t.me/G/1"', text)
        self.assertTrue(text.endswith("🦅\n"))

    def test_cover_option_overrides_the_existing_one(self):
        args = script.parse_args([DATE, "--cover", "https://other/c.jpg"])
        with patched_config(**CONFIG), patch("scripts.regenerate_article.requests.head", return_value=_head()), \
             patch("scripts.regenerate_article.existing_cover") as existing, \
             patch("scripts.regenerate_article.generate_astro_article", return_value=GOOD_ARTICLE), \
             patch("scripts.regenerate_article.astro.publish_article", return_value=("l", "b")) as publish:
            script.run(args)

        existing.assert_not_called()
        self.assertEqual(publish.call_args.args[4], "https://other/c.jpg")

    def test_a_bad_article_is_retried_and_the_good_one_is_used(self):
        code, gen, publish, _merge = self.run_script(DATE, articles=("### Solo titolo\n", GOOD_ARTICLE))

        self.assertEqual(code, 0)
        self.assertEqual(gen.call_count, 2)
        self.assertEqual(publish.call_args.args[1], GOOD_ARTICLE)

    def test_it_gives_up_after_three_bad_attempts_without_publishing(self):
        code, gen, publish, merge = self.run_script(DATE, "--publish", articles=("### x\n", None, "### y\n"))

        self.assertEqual(code, 1)
        self.assertEqual(gen.call_count, 3)
        publish.assert_not_called()
        merge.assert_not_called()

    def test_no_events_for_the_date_exits_cleanly(self):
        code, gen, publish, _merge = self.run_script("01-01-2030")

        self.assertEqual(code, 1)
        gen.assert_not_called()
        publish.assert_not_called()

    def test_invalid_date_and_missing_settings_are_refused(self):
        self.assertEqual(self.run_script("2026-10-28")[0], 1)
        with patched_config(**{**CONFIG, "ASTRO_GITHUB_TOKEN": None}):
            self.assertEqual(script.run(script.parse_args([DATE])), 1)
            # A dry run does not need the GitHub token
            self.assertEqual(script.missing_settings(True), [])
            self.assertEqual(script.missing_settings(False), ["ASTRO_GITHUB_TOKEN"])

    def test_publish_cannot_be_combined_with_dry_run(self):
        with self.assertRaises(SystemExit):
            script.parse_args([DATE, "--publish", "--dry-run"])


if __name__ == "__main__":
    unittest.main()
