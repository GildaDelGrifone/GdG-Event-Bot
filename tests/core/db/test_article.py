import unittest

from core import db
from core.db.connection import fetch_one
from core.db.schema import COLUMN_MIGRATIONS
from tests.support.db import TempDBMixin, create_event


class TestArticleInfo(TempDBMixin, unittest.TestCase):
    def test_columns_are_migrated(self):
        self.assertIn("article_backend", COLUMN_MIGRATIONS["events"])
        row = fetch_one("SELECT article_backend, article_ref FROM events LIMIT 1")
        self.assertIsNone(row)

    def test_article_info_round_trips_by_date_and_backend(self):
        first = create_event(normalized_date="23-10-2026")
        second = create_event(normalized_date="23-10-2026")
        other = create_event(normalized_date="24-10-2026")

        db.update_events_article_info([first, second], "astro", "serata/x", "https://gh/x")

        self.assertEqual(db.get_article_ref_for_date("23-10-2026", "astro"), "serata/x")
        self.assertIsNone(db.get_article_ref_for_date("23-10-2026", "wordpress"))
        self.assertIsNone(db.get_article_ref_for_date("24-10-2026", "astro"))
        self.assertEqual(db.get_event(first)["wp_post_url"], "https://gh/x")
        self.assertIsNone(db.get_event(other)["article_ref"])

    def test_clear_article_info_only_touches_the_given_date(self):
        mine = create_event(normalized_date="23-10-2026")
        other = create_event(normalized_date="24-10-2026")
        db.update_events_article_info([mine], "astro", "serata/x", "link")
        db.update_events_article_info([other], "astro", "serata/y", "link")

        db.clear_article_info_for_date("23-10-2026")

        self.assertIsNone(db.get_article_ref_for_date("23-10-2026", "astro"))
        self.assertEqual(db.get_article_ref_for_date("24-10-2026", "astro"), "serata/y")
        self.assertIsNone(db.get_event(mine)["wp_post_url"])

    def test_clear_wp_post_info_only_touches_that_post(self):
        first, second = create_event(), create_event()
        db.update_events_wp_info([first], 10, "https://wp/10")
        db.update_events_wp_info([second], 11, "https://wp/11")

        db.clear_wp_post_info(10)

        self.assertIsNone(db.get_event(first)["wp_post_id"])
        self.assertEqual(db.get_event(second)["wp_post_id"], 11)


if __name__ == "__main__":
    unittest.main()
