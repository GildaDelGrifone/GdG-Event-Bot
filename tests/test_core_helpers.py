import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import core.db as db
from core import config


class TempDBTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = os.path.join(self.temp_dir.name, "test.db")
        db.init_db()

    def tearDown(self):
        config.DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()


class TestDbSafe(unittest.TestCase):
    def test_returns_fresh_default_and_logs(self):
        from core.db.connection import db_safe

        @db_safe(default=list)
        def broken():
            raise RuntimeError("boom")

        with patch("core.db.connection.logger") as log:
            first, second = broken(), broken()
        self.assertEqual(first, [])
        self.assertIsNot(first, second)
        self.assertIn("broken", log.error.call_args.args[0])


class TestNormalizeIdentity(unittest.TestCase):
    def test_rules(self):
        from core.db.reservations import normalize_identity
        self.assertEqual(normalize_identity("@mario", None), ("mario", None))
        self.assertEqual(normalize_identity("Mario Rossi", None), (None, "Mario Rossi"))
        self.assertEqual(normalize_identity("@", "  "), (None, None))
        self.assertEqual(normalize_identity(None, " Anna "), (None, "Anna"))


class TestSeatBookkeeping(TempDBTestCase):
    def test_partial_and_full_subscriber_removal_keep_counters_in_sync(self):
        event_id = db.insert_event({"title": "T", "max_seats": 5, "seats": "5/5"}, None, "raw")
        self.assertTrue(db.admin_add_subscriber(event_id, "@mario", seats=3)[0])
        self.assertEqual(db.get_event(event_id)["seats"], "2/5")

        ok, msg = db.admin_remove_subscriber(event_id, "mario", seats=1)
        self.assertTrue(ok)
        self.assertIn("Rimossi 1", msg)
        self.assertEqual(db.get_event(event_id)["booked_seats"], 2)

        db.admin_remove_subscriber(event_id, "mario")
        self.assertEqual(db.get_event(event_id)["seats"], "5/5")
        self.assertEqual(db.get_reservations_for_event(event_id), [])

    def test_capacity_and_cancelled_checks(self):
        event_id = db.insert_event({"title": "T", "max_seats": 1}, None, "raw")
        self.assertTrue(db.book_seat(event_id, 1, username="a")[0])
        self.assertEqual(db.book_seat(event_id, 2, username="b"), (False, "Nessun posto disponibile."))
        db.update_event_status(event_id, "cancelled")
        self.assertEqual(db.unbook_seat(event_id, 1), (False, "Evento annullato."))
        self.assertEqual(db.book_seat(999, 1), (False, "Evento non trovato."))

    def test_status_queries_use_string_literals(self):
        event_id = db.insert_event({"title": "T", "normalized_date": "07-10-2026"}, None, "raw")
        db.update_event_status(event_id, "approved")
        self.assertEqual([e["id"] for e in db.get_pending_events_for_recap("07-10-2026")], [event_id])
        self.assertEqual([e["id"] for e in db.get_approved_events_for_date("07/10/2026")], [event_id])


class TestScheduledEvents(TempDBTestCase):
    def test_content_update_only_touches_given_columns(self):
        sched_id = db.insert_scheduled_event("Titolo", "testo", image_path="/a.jpg", schedule_days=["Lunedì"])
        db.update_scheduled_event_content(sched_id, "nuovo testo")
        ev = db.get_scheduled_event(sched_id)
        self.assertEqual((ev["text"], ev["image_path"], ev["title"]), ("nuovo testo", "/a.jpg", "Titolo"))
        self.assertEqual(ev["schedule_days"], ["Lunedì"])

        db.update_scheduled_event_content(sched_id, "t2", title="Nuovo")
        self.assertEqual(db.get_scheduled_event(sched_id)["title"], "Nuovo")

    def test_matches_weekday_or_specific_date(self):
        weekly = db.insert_scheduled_event("A", "a", schedule_days=["Mercoledì"])
        dated = db.insert_scheduled_event("B", "b", specific_date="Venerdì 09-10-2026 21:00")
        db.insert_scheduled_event("C", "c", schedule_days=["Lunedì"])
        ids = {ev["id"] for ev in db.get_scheduled_events_for_date("09-10-2026", "mercoledì")}
        self.assertEqual(ids, {weekly, dated})


class TestAiParserHelpers(unittest.TestCase):
    def test_seat_safety_net(self):
        from core.ai_parser import _apply_seat_safety_net
        data = {"max_seats": 5, "seats": "4/5", "booked_seats": 1}
        _apply_seat_safety_net(data, "Posti liberi: 4/5")
        self.assertEqual(data, {"max_seats": 4, "seats": "4/4", "booked_seats": 0})

        data = {}
        _apply_seat_safety_net(data, "Posti: 0")
        self.assertEqual(data["seats"], "0/0 Completo")

        data = {"seats": "no limit"}
        _apply_seat_safety_net(data, "Nessuna indicazione")
        self.assertEqual(data, {"seats": "no limit"})

    def test_coerce_bool(self):
        from core.ai_parser import coerce_bool
        self.assertTrue(coerce_bool(" Sì "))
        self.assertFalse(coerce_bool("no"))
        self.assertTrue(coerce_bool(1))
        self.assertFalse(coerce_bool(None))

    def test_generate_text_maps_quota_errors(self):
        from core.ai_parser import GeminiQuotaError, generate_text
        with patch("core.ai_parser.genai.GenerativeModel") as model:
            model.return_value.generate_content.side_effect = Exception("429 quota exceeded")
            with self.assertRaises(GeminiQuotaError):
                generate_text("prompt")


class TestRepostDigest(unittest.TestCase):
    def test_titles_are_html_escaped(self):
        from core.scheduler.reposts import format_reposts_digest
        text = format_reposts_digest([{"id": 3, "title": "D&D <Oneshot>"}], "Lunedì", "05-10-2026")
        self.assertIn("D&amp;D &lt;Oneshot&gt;", text)
        self.assertIn("/event_schedule_invoke 3", text)


class TestWordPressClient(unittest.TestCase):
    def test_posts_carry_timeout_and_auth(self):
        from core.wordpress import update_article_status
        response = MagicMock(status_code=200)
        with patch.object(config, "WP_URL", "https://example.com/"), \
             patch.object(config, "WP_USERNAME", "u"), \
             patch.object(config, "WP_APP_PASSWORD", "p"), \
             patch("core.wordpress.client.requests.post", return_value=response) as post:
            self.assertTrue(update_article_status(7, "publish"))
        self.assertEqual(post.call_args.args[0], "https://example.com/wp-json/wp/v2/posts/7")
        self.assertIn("timeout", post.call_args.kwargs)
        self.assertTrue(post.call_args.kwargs["headers"]["Authorization"].startswith("Basic "))

    def test_missing_credentials_short_circuit(self):
        from core.wordpress import upload_media
        with patch.object(config, "WP_URL", None), patch("core.wordpress.client.requests.post") as post:
            self.assertIsNone(upload_media("/nope.jpg"))
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
