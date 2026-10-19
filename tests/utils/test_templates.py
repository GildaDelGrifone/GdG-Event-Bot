import unittest

import core.db as db
from tests.support.db import TempDBMixin, create_deep_link_event, create_no_username_event
from utils.templates import (
    format_discussion_booking_message,
    format_event_participants_message,
    format_event_seats,
    format_instagram_story,
    format_public_event_message,
    format_reservation_subscriber_display,
    recap_generate_text,
    recap_links_text,
)


class TestRoleplayTypeFormatting(unittest.TestCase):
    def test_format_public_event_message_rpg(self):
        text = format_public_event_message({
            "title": "D&D Session", "date": "05-09-2026 21:00", "system": "D&D 5e", "host": "Matt Mercer",
            "max_seats": 5, "booked_seats": 2, "is_roleplay": 1,
        })
        self.assertIn("👑 Master: Matt Mercer", text)
        self.assertNotIn("👑 Host:", text)

    def test_format_public_event_message_non_rpg(self):
        text = format_public_event_message({
            "title": "Catan Night", "date": "05-09-2026 21:00", "system": "Settlers of Catan", "host": "Klaus",
            "max_seats": 4, "booked_seats": 1, "is_roleplay": 0,
        })
        self.assertIn("👑 Host: Klaus", text)
        self.assertNotIn("👑 Master:", text)

    def test_format_public_event_message_default_fallback(self):
        text = format_public_event_message({"title": "Boardgame", "host": "Admin"})
        self.assertIn("👑 Host: Admin", text)

    def test_format_public_event_message_bold_title_and_plain_details(self):
        text = format_public_event_message({
            "title": "D&D Session", "date": "05-09-2026 21:00", "system": "D&D 5e", "host": "Matt Mercer",
            "max_seats": 5, "booked_seats": 2, "extra_info": "Portare dadi e scheda", "description": "Avventura epica",
        })
        # Title must use <b> and not **
        self.assertIn("📣 <b>D&amp;D Session</b>", text)
        self.assertNotIn("**", text)
        # Details label must not have ** and must not be bolded
        self.assertIn("\n🏷️ Dettagli:\nPortare dadi e scheda\n", text)
        self.assertNotIn("<b>Dettagli:</b>", text)
        self.assertNotIn("**Dettagli:**", text)

    def test_format_public_event_message_cancelled_bold(self):
        text = format_public_event_message({"title": "Game Night", "status": "cancelled", "max_seats": 4,
                                            "extra_info": "Info extra"})
        self.assertIn("📣 <b>❌ [ANNULLATO] Game Night</b>", text)
        self.assertNotIn("**", text)
        self.assertIn("\n🏷️ Dettagli:\nInfo extra\n", text)

    def test_format_instagram_story_rpg(self):
        text = format_instagram_story({"title": "Call of Cthulhu", "date": "06-09-2026", "system": "CoC 7e",
                                       "host": "Lovecraft", "max_seats": 4, "is_roleplay": True})
        self.assertIn("Master: Lovecraft", text)
        self.assertNotIn("Host: Lovecraft", text)

    def test_format_instagram_story_non_rpg(self):
        text = format_instagram_story({"title": "Terraforming Mars", "date": "06-09-2026", "system": "Board Game",
                                       "host": "Elon", "max_seats": 5, "is_roleplay": False})
        self.assertIn("Host: Elon", text)
        self.assertNotIn("Master: Elon", text)


class TestFormatEventSeats(unittest.TestCase):
    def test_format_event_seats_limited(self):
        self.assertEqual(format_event_seats({"booked_seats": 2, "max_seats": 5, "status": "approved"}), "3/5")

    def test_format_event_seats_full(self):
        self.assertEqual(format_event_seats({"booked_seats": 5, "max_seats": 5, "status": "approved"}), "0/5 Completo")

    def test_format_event_seats_overbooked(self):
        self.assertEqual(format_event_seats({"booked_seats": 6, "max_seats": 5, "status": "approved"}), "0/5 Completo")

    def test_format_event_seats_unlimited(self):
        self.assertEqual(format_event_seats({"booked_seats": 0, "max_seats": None, "status": "approved"}),
                         "Nessun limite")
        self.assertEqual(format_event_seats({"booked_seats": 3, "max_seats": None, "status": "approved"}),
                         "Nessun limite (Prenotati: 3)")

    def test_format_event_seats_cancelled(self):
        self.assertEqual(format_event_seats({"booked_seats": 2, "max_seats": 4, "status": "cancelled"}),
                         "0/4 [ANNULLATO]")
        self.assertEqual(format_event_seats({"booked_seats": 2, "max_seats": None, "status": "cancelled"}),
                         "0 (Nessun limite) [ANNULLATO]")


class TestRecapTexts(unittest.TestCase):
    def test_recap_generate_text_event_titles_bold(self):
        events = [
            {"title": "Avventura D&D", "system": "D&D 5e", "booked_seats": 2, "max_seats": 5, "status": "approved"},
            {"title": "Cyberpunk Red", "system": "Cyberpunk", "booked_seats": 0, "max_seats": 4, "status": "cancelled"},
            {"title": "One Shot Giochi Liberi", "system": None, "booked_seats": 3, "max_seats": None,
             "status": "approved"},
        ]
        text = recap_generate_text("Venerdì", "05-09-2026", events)
        self.assertIn("- <b>Avventura D&amp;D</b> (D&amp;D 5e) : 3/5", text)
        self.assertIn("- ❌ <b>Cyberpunk Red</b> (Cyberpunk) : 0/4 [ANNULLATO]", text)
        self.assertIn("- <b>One Shot Giochi Liberi</b> : Nessun limite (Prenotati: 3)", text)

    def test_recap_links_text_event_titles_bold_and_linked(self):
        events = [
            {"title": "Avventura D&D", "system": "D&D 5e", "message_link": "https://t.me/c/123/456", "status": "approved"},
            {"title": "Call of Cthulhu", "system": "CoC", "message_link": None, "status": "approved"},
            {"title": "Cancelled Event", "system": "Test", "message_link": "https://t.me/c/123/789", "status": "cancelled"},
        ]
        links_text = recap_links_text(events)
        self.assertIn('- <a href="https://t.me/c/123/456"><b>Avventura D&amp;D</b></a> (D&amp;D 5e)', links_text)
        self.assertIn('- <b>Call of Cthulhu</b> (CoC)', links_text)
        self.assertNotIn("Cancelled Event", links_text)


class TestEventParticipantsMessage(TempDBMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.event = db.get_event(create_deep_link_event())

    def test_format_event_participants_message_empty(self):
        msg = format_event_participants_message(self.event, [])
        self.assertIn("One-Shot D&amp;D &lt;Special&gt;", msg)
        self.assertIn("Posti occupati: <b>0/4</b>", msg)
        self.assertIn("Nessun partecipante iscritto al momento.", msg)

    def test_format_event_participants_message_with_reservations(self):
        reservations = [
            {"username": "mario", "user_id": 101, "seats_booked": 1},
            {"username": "@luigi<boss>", "user_id": 102, "seats_booked": 2},
            {"username": "", "user_id": 103, "seats_booked": 1},
        ]
        msg = format_event_participants_message(self.event, reservations)
        self.assertIn("<b>@mario</b>", msg)
        self.assertIn("<b>@luigi&lt;boss&gt;</b> (2 posti)", msg)
        self.assertIn("<b>ID:103</b>", msg)

    def test_format_event_participants_message_cancelled(self):
        self.event["status"] = "cancelled"
        msg = format_event_participants_message(self.event, [])
        self.assertIn("❌ <i>[ANNULLATO]</i>", msg)


class TestSubscribersWithoutUsername(TempDBMixin, unittest.TestCase):
    def test_format_reservation_subscriber_display(self):
        res1 = {"username": "steucestari", "user_id": 1609031146, "full_name": None}
        self.assertEqual(format_reservation_subscriber_display(res1, as_html=True), "@steucestari")
        self.assertEqual(format_reservation_subscriber_display(res1, as_html=False), "@steucestari")

        res2 = {"username": None, "user_id": 8893283822, "full_name": "Lorenzo Duarte"}
        self.assertEqual(format_reservation_subscriber_display(res2, as_html=True),
                         '<a href="tg://user?id=8893283822">Lorenzo Duarte</a>')
        self.assertEqual(format_reservation_subscriber_display(res2, as_html=False), "Lorenzo Duarte")

        res3 = {"username": "Lorenzo Duarte", "user_id": 8893283822, "full_name": None}
        self.assertEqual(format_reservation_subscriber_display(res3, as_html=True),
                         '<a href="tg://user?id=8893283822">Lorenzo Duarte</a>')
        self.assertEqual(format_reservation_subscriber_display(res3, as_html=False), "Lorenzo Duarte")

        res4 = {"username": "", "user_id": 99999, "full_name": None}
        self.assertEqual(format_reservation_subscriber_display(res4, as_html=True), "ID:99999")
        self.assertEqual(format_reservation_subscriber_display(res4, as_html=False), "ID:99999")

    def test_format_event_participants_message_no_at_for_non_username(self):
        event = db.get_event(create_no_username_event())
        reservations = [
            {"username": "steucestari", "user_id": 1609031146, "full_name": None, "seats_booked": 1},
            {"username": None, "user_id": 8893283822, "full_name": "Lorenzo Duarte", "seats_booked": 1},
            {"username": "ChicoMalo96", "user_id": 297895076, "full_name": None, "seats_booked": 1},
        ]
        msg = format_event_participants_message(event, reservations)

        self.assertIn("<b>@steucestari</b>", msg)
        self.assertIn("<b>@ChicoMalo96</b>", msg)
        self.assertNotIn("@Lorenzo", msg)
        self.assertIn('<b><a href="tg://user?id=8893283822">Lorenzo Duarte</a></b>', msg)


class TestEventbriteTemplates(unittest.TestCase):
    def test_eventbrite_subscribers_are_prefixed_in_both_modes(self):
        res = {"source": "eventbrite", "username": None, "user_id": None, "full_name": "Mario <R.>"}
        self.assertEqual(format_reservation_subscriber_display(res, as_html=True), "🎟️ Mario &lt;R.&gt;")
        self.assertEqual(format_reservation_subscriber_display(res, as_html=False), "🎟️ Mario <R.>")
        self.assertEqual(format_reservation_subscriber_display({"source": "eventbrite"}), "🎟️ Partecipante Eventbrite")

    def test_telegram_subscribers_are_unchanged(self):
        res = {"source": "telegram", "username": "mario", "user_id": 1, "full_name": None}
        self.assertEqual(format_reservation_subscriber_display(res), "@mario")

    def test_participants_message_lists_eventbrite_bookings(self):
        event = {"id": 1, "title": "T", "booked_seats": 3, "max_seats": 4}
        reservations = [
            {"source": "eventbrite", "full_name": "Mario R.", "seats_booked": 2},
            {"source": "telegram", "username": "luigi", "user_id": 2, "seats_booked": 1},
        ]
        message = format_event_participants_message(event, reservations)
        self.assertIn("<b>🎟️ Mario R.</b> (2 posti)", message)
        self.assertIn("<b>@luigi</b>", message)

    def test_discussion_booking_message(self):
        plain = "👇 Gestisci qui la tua prenotazione!"
        self.assertEqual(format_discussion_booking_message({}), plain)
        self.assertEqual(format_discussion_booking_message(None), plain)
        live = {"eventbrite_url": "https://eb.example/e/1?a=1&b=2", "eventbrite_status": "live"}
        self.assertEqual(
            format_discussion_booking_message(live),
            plain + '\n🎟️ Prenota anche su Eventbrite: <a href="https://eb.example/e/1?a=1&amp;b=2">link</a>')
        for status in ("draft", "unpublished", "closed", "canceled", None):
            with self.subTest(status=status):
                self.assertEqual(format_discussion_booking_message({**live, "eventbrite_status": status}), plain)
        self.assertEqual(format_discussion_booking_message({"eventbrite_status": "live"}), plain)


if __name__ == "__main__":
    unittest.main()
