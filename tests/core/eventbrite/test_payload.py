import unittest
from datetime import datetime, timezone

from core.eventbrite.payload import (
    attendee_display_name,
    attendees_dashboard_url,
    dashboard_url,
    description_modules,
    event_name,
    event_payload,
    event_start_end,
    ticket_quantity,
)
from tests.support.config import eventbrite_credentials

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def event(**overrides):
    return {
        "title": "Avventura D&D", "date": "Venerdì 06-11-2026 21:00", "normalized_date": "06-11-2026",
        "system": "D&D 5e", "host": "Master <DM>", "description": "Una grande avventura", "extra_info": "",
        "is_roleplay": 1, "booked_seats": 0, "max_seats": 4, "status": "approved", "message_link": None,
        **overrides,
    }


class TestStartEnd(unittest.TestCase):
    def test_time_from_date_string_converted_to_utc(self):
        with eventbrite_credentials():
            start, end = event_start_end(event(), now=NOW)
        self.assertEqual(start, datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc))  # CET = UTC+1
        self.assertEqual(end, datetime(2026, 11, 7, 0, 0, tzinfo=timezone.utc))

    def test_summer_time_uses_utc_plus_two(self):
        with eventbrite_credentials():
            start, _ = event_start_end(event(date="Sabato 04-07-2026 21:00", normalized_date="04-07-2026"),
                                       now=datetime(2026, 6, 1, tzinfo=timezone.utc))
        self.assertEqual(start.hour, 19)

    def test_default_time_and_duration_come_from_config(self):
        with eventbrite_credentials(EVENTBRITE_DEFAULT_START_TIME="18:30", EVENTBRITE_EVENT_DURATION_HOURS=2.5):
            start, end = event_start_end(event(date="Venerdì 06-11-2026"), now=NOW)
        self.assertEqual((start.hour, start.minute), (17, 30))
        self.assertEqual((end - start).total_seconds(), 2.5 * 3600)

    def test_past_and_missing_dates_raise(self):
        with eventbrite_credentials():
            with self.assertRaisesRegex(ValueError, "data nel passato"):
                event_start_end(event(date="Venerdì 06-11-2020 21:00", normalized_date="06-11-2020"))
            with self.assertRaisesRegex(ValueError, "data mancante"):
                event_start_end(event(date="da definire", normalized_date=""))


class TestEventPayload(unittest.TestCase):
    def test_payload_fields(self):
        with eventbrite_credentials(EVENTBRITE_ORGANIZER_ID="org-9", EVENTBRITE_LISTED=False):
            payload = event_payload(event(date="Venerdì 06-11-2099 21:00", normalized_date="06-11-2099"))
        self.assertEqual(payload["name"], {"html": "Avventura D&amp;D"})
        self.assertEqual(payload["summary"], "Una grande avventura")
        self.assertEqual(payload["venue_id"], "venue1")
        self.assertEqual(payload["organizer_id"], "org-9")
        self.assertEqual((payload["currency"], payload["listed"]), ("EUR", False))
        self.assertTrue(payload["shareable"] and payload["show_remaining"])
        self.assertEqual(payload["start"], {"timezone": "Europe/Rome", "utc": "2099-11-06T20:00:00Z"})
        self.assertEqual(payload["end"]["utc"], "2099-11-07T00:00:00Z")

    def test_without_dates_or_organizer(self):
        with eventbrite_credentials():
            payload = event_payload(event(date="Venerdì 06-11-2020 21:00", normalized_date="06-11-2020"),
                                    include_dates=False)
        self.assertNotIn("start", payload)
        self.assertNotIn("end", payload)
        self.assertNotIn("organizer_id", payload)

    def test_cancelled_prefix_and_truncation(self):
        self.assertEqual(event_name(event(status="cancelled")), "[ANNULLATO] Avventura D&D")
        name = event_name(event(title="x" * 200, status="cancelled"))
        self.assertEqual(len(name), 75)
        self.assertTrue(name.startswith("[ANNULLATO] x") and name.endswith("…"))

    def test_truncation_happens_before_escaping(self):
        with eventbrite_credentials():
            payload = event_payload(event(title="&" * 100), include_dates=False)
        self.assertEqual(payload["name"]["html"].count("&amp;"), 74)
        self.assertNotIn("&amp", payload["name"]["html"].replace("&amp;", ""))

    def test_summary_falls_back_to_system_and_is_capped(self):
        with eventbrite_credentials():
            self.assertEqual(event_payload(event(description=""), include_dates=False)["summary"], "D&D 5e")
            long = event_payload(event(description="parola " * 100), include_dates=False)["summary"]
        self.assertEqual(len(long), 140)


class TestDescriptionModules(unittest.TestCase):
    def html(self, **overrides):
        modules = description_modules(event(**overrides))
        self.assertEqual(len(modules), 1)
        self.assertEqual(modules[0]["type"], "text")
        body = modules[0]["data"]["body"]
        self.assertEqual((body["type"], body["alignment"]), ("text", "left"))
        return body["text"]

    def test_content_and_escaping(self):
        text = self.html(extra_info="Principianti\nTW: horror <b>", message_link="https://t.me/c/1/2")
        self.assertIn("<p><b>Sistema:</b> D&amp;D 5e</p>", text)
        self.assertIn("<p><b>Master:</b> Master &lt;DM&gt;</p>", text)
        self.assertIn("<p><b>Dettagli:</b></p><p>Principianti</p><p>TW: horror &lt;b&gt;</p>", text)
        self.assertIn("<p>Una grande avventura</p>", text)
        self.assertIn("<em>Gilda del Grifone, Via Ada Negri 8/A, Torino</em>", text)
        self.assertIn('<a href="https://t.me/c/1/2">Evento su Telegram</a>', text)

    def test_host_label_follows_roleplay_flag_and_empty_parts_are_skipped(self):
        text = self.html(is_roleplay=0, system="", extra_info="", description="", message_link=None)
        self.assertIn("<b>Host:</b>", text)
        for absent in ("Sistema", "Dettagli", "Telegram"):
            self.assertNotIn(absent, text)

    def test_only_allowed_tags(self):
        import re
        text = self.html(extra_info="a\nb", message_link="https://t.me/x")
        self.assertLessEqual(set(re.findall(r"</?([a-z]+)", text)), {"p", "b", "em", "ul", "li", "a"})


class TestTicketQuantity(unittest.TestCase):
    def test_limited_event_mirrors_free_telegram_seats(self):
        self.assertEqual(ticket_quantity(event(max_seats=4, booked_seats=0), 0, 50), 4)
        self.assertEqual(ticket_quantity(event(max_seats=4, booked_seats=1), 0, 50), 3)
        # 1 Telegram + 2 Eventbrite booked: 1 seat is still free, so Eventbrite sold(2) + 1 = 3 total
        self.assertEqual(ticket_quantity(event(max_seats=4, booked_seats=3), 2, 50), 3)

    def test_full_event_is_sold_out_on_eventbrite(self):
        self.assertEqual(ticket_quantity(event(max_seats=4, booked_seats=4), 0, 50), 0)
        self.assertEqual(ticket_quantity(event(max_seats=4, booked_seats=4), 2, 50), 2)

    def test_unlimited_event_uses_configured_capacity(self):
        self.assertEqual(ticket_quantity(event(max_seats=None, booked_seats=3), 0, 50), 47)

    def test_eventbrite_seats_above_capacity_are_never_undercut(self):
        self.assertEqual(ticket_quantity(event(max_seats=4, booked_seats=6), 6, 50), 6)
        self.assertEqual(ticket_quantity(event(max_seats=2, booked_seats=0), 5, 50), 5)

    def test_cancelled_event_closes_sales(self):
        self.assertEqual(ticket_quantity(event(status="cancelled", max_seats=4), 3, 50), 3)
        self.assertEqual(ticket_quantity(event(status="cancelled", max_seats=4), 0, 50), 0)


class TestMisc(unittest.TestCase):
    def test_attendee_display_name(self):
        cases = [
            ({"first_name": "Mario", "last_name": "rossi", "name": "Mario Rossi"}, "Mario R."),
            ({"first_name": " Mario ", "last_name": ""}, "Mario"),
            ({"name": "Mario Rossi"}, "Mario Rossi"),
            ({}, "Partecipante Eventbrite"),
            (None, "Partecipante Eventbrite"),
        ]
        for profile, expected in cases:
            with self.subTest(profile=profile):
                self.assertEqual(attendee_display_name(profile), expected)

    def test_dashboard_urls(self):
        self.assertEqual(dashboard_url("42"), "https://www.eventbrite.com/myevent?eid=42")
        self.assertEqual(attendees_dashboard_url("42"), "https://www.eventbrite.com/attendees-manage?eid=42")


if __name__ == "__main__":
    unittest.main()
