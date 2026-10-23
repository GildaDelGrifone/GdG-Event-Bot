import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import core.db as db
from core.eventbrite.client import EventbriteError
from scripts.eventbrite_inspect import fetch_snapshot, main, render
from tests.support.config import eventbrite_credentials, patched_config
from tests.support.db import TempDBMixin, create_event

EVENT = {"status": "live", "ticket_classes": [
    {"name": "Posto", "quantity_total": 4, "quantity_sold": 3, "quantity_pending": 0},
]}


def attendee(**flags):
    # Personal data that must never be printed
    return {"profile": {"first_name": "Mario", "last_name": "Rossi", "email": "mario@example.com"}, **flags}


ORDERS = [
    {"id": 111, "status": "placed", "attendees": [attendee(), attendee()]},
    {"id": 222, "status": "refunded", "attendees": [attendee(cancelled=True), attendee(refunded=True)]},
    {"id": 333, "status": "placed", "attendees": [attendee(), attendee(cancelled=True)]},
]


def run(*argv, **kwargs):
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(list(argv), **kwargs)
    return code, out.getvalue()


class InspectCase(unittest.TestCase):
    def setUp(self):
        self.event = EVENT
        self.orders = ORDERS
        patch("scripts.eventbrite_inspect.eb_get", side_effect=lambda *a, **k: self.event).start()
        patch("scripts.eventbrite_inspect.paginate", side_effect=lambda *a, **k: iter(self.orders)).start()
        patch("scripts.eventbrite_inspect.bot_seat_count", return_value=None).start()
        self.addCleanup(patch.stopall)


class TestSnapshot(InspectCase):
    def test_counts_orders_and_attendees(self):
        snapshot = fetch_snapshot("eb1")
        self.assertEqual((snapshot["status"], snapshot["sold"], snapshot["active"]), ("live", 3, 3))
        self.assertEqual(snapshot["classes"], [{"name": "Posto", "total": 4, "sold": 3, "pending": 0}])
        self.assertEqual([(o["id"], o["attendees"], o["cancelled"], o["refunded"], o["active"]) for o in snapshot["orders"]],
                         [("111", 2, 0, 0, 2), ("222", 2, 1, 1, 0), ("333", 2, 1, 0, 1)])

    def test_missing_quantities_count_as_zero(self):
        self.event = {"status": "draft", "ticket_classes": [{"name": "Posto", "quantity_total": 4, "quantity_sold": None}]}
        self.orders = []
        self.assertEqual(fetch_snapshot("eb1")["sold"], 0)

    def test_event_without_ticket_classes(self):
        self.event = {"status": "live"}
        self.orders = []
        self.assertEqual(fetch_snapshot("eb1")["classes"], [])

    def test_render_shows_the_verdict_and_never_personal_data(self):
        text = "\n".join(render(fetch_snapshot("eb1")))
        self.assertIn("Biglietto «Posto»: totale 4, venduti 3", text)
        self.assertIn("ordine 222: stato refunded, partecipanti 2 (annullati 1, rimborsati 1, attivi 0)", text)
        self.assertIn("quantity_sold 3 vs partecipanti attivi 3 → UGUALI", text)
        for private in ("Mario", "Rossi", "mario@example.com"):
            self.assertNotIn(private, text)

    def test_render_flags_a_difference_and_shows_pending(self):
        self.event = {"status": "live", "ticket_classes": [
            {"name": "Posto", "quantity_total": 4, "quantity_sold": 5, "quantity_pending": 1}]}
        text = "\n".join(render(fetch_snapshot("eb1")))
        self.assertIn("in attesa 1", text)
        self.assertIn("quantity_sold 5 vs partecipanti attivi 3 → DIVERSI", text)

    def test_render_without_orders(self):
        self.orders = []
        self.event = {"status": "live", "ticket_classes": []}
        text = "\n".join(render(fetch_snapshot("eb1")))
        self.assertIn("Ordini (0):\n  nessuno", text)
        self.assertIn("quantity_sold 0 vs partecipanti attivi 0 → UGUALI", text)


class TestMain(InspectCase):
    def test_single_snapshot(self):
        with eventbrite_credentials():
            code, out = run("eb1")
        self.assertEqual(code, 0)
        self.assertIn("quantity_sold 3 vs partecipanti attivi 3", out)

    def test_missing_token(self):
        with patched_config(EVENTBRITE_TOKEN=None):
            code, out = run("eb1")
        self.assertEqual(code, 1)
        self.assertIn("EVENTBRITE_TOKEN", out)

    def test_api_error_exits_non_zero(self):
        with eventbrite_credentials(), patch("scripts.eventbrite_inspect.eb_get",
                                             side_effect=EventbriteError(404, "NOT_FOUND", "no such event")):
            code, out = run("nope")
        self.assertEqual(code, 1)
        self.assertIn("NOT_FOUND", out)

    def test_watch_has_a_minimum_interval(self):
        with self.assertRaises(SystemExit), patch("sys.stderr", io.StringIO()):
            main(["eb1", "--watch", "5"])

    def test_watch_prints_only_when_something_changes(self):
        states = [
            ({"status": "live", "ticket_classes": [{"name": "Posto", "quantity_total": 4, "quantity_sold": 1}]}, ORDERS[:1]),
            ({"status": "live", "ticket_classes": [{"name": "Posto", "quantity_total": 4, "quantity_sold": 1}]}, ORDERS[:1]),
            ({"status": "live", "ticket_classes": [{"name": "Posto", "quantity_total": 4, "quantity_sold": 0}]}, ORDERS[:1]),
        ]
        rounds = []

        def sleep(seconds):
            rounds.append(seconds)
            if len(rounds) >= len(states):
                raise KeyboardInterrupt
            self.event, self.orders = states[len(rounds)]

        self.event, self.orders = states[0]
        with eventbrite_credentials():
            code, out = run("eb1", "--watch", "20", sleep=sleep)

        self.assertEqual((code, rounds), (0, [20, 20, 20]))
        self.assertEqual(out.count("Biglietto «Posto»"), 2)  # first snapshot + the change; the repeat is silent
        self.assertIn("venduti 1", out)
        self.assertIn("venduti 0", out)
        self.assertIn("Interrotto.", out)

    def test_watch_survives_a_transient_error(self):
        calls = []

        def flaky_get(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise EventbriteError(429, "HIT_RATE_LIMIT", "slow down")
            return self.event

        def sleep(seconds):
            if len(calls) >= 2:
                raise KeyboardInterrupt

        with eventbrite_credentials(), patch("scripts.eventbrite_inspect.eb_get", side_effect=flaky_get):
            code, out = run("eb1", "--watch", "20", sleep=sleep)

        self.assertEqual(code, 0)
        self.assertIn("HIT_RATE_LIMIT", out)
        self.assertIn("quantity_sold 3", out)


class TestBotComparison(TempDBMixin, unittest.TestCase):
    def test_bot_line_compares_the_stored_seats(self):
        from scripts.eventbrite_inspect import bot_seat_count

        event_id = create_event(status="approved", max_seats=6, seats="6/6")
        db.set_eventbrite_info(event_id, eventbrite_event_id="eb1")
        db.apply_eventbrite_order(event_id, "o1", "Mario R.", 2)

        self.assertEqual(bot_seat_count("eb1"), (event_id, 2))
        self.assertIsNone(bot_seat_count("unknown"))

        snapshot = {"status": "live", "classes": [], "sold": 3, "orders": [], "active": 0, "bot": (event_id, 2)}
        self.assertIn(f"Il bot ha registrato 2 posti Eventbrite per l'evento #{event_id} (vs quantity_sold 3 → DIVERSI)",
                      render(snapshot))

    def test_unknown_when_the_database_is_unavailable(self):
        from scripts.eventbrite_inspect import bot_seat_count
        with patched_config(DB_PATH="/nonexistent/dir/x.db"):
            self.assertIsNone(bot_seat_count("eb1"))


if __name__ == "__main__":
    unittest.main()
