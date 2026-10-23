#!/usr/bin/env python3
"""
Read-only inspection of an Eventbrite event: ticket quantities versus orders and attendees.

Useful to check how `quantity_sold` behaves, e.g. whether it goes down when an order is cancelled:
place a test order, run this script, cancel the order, run it again (or keep it running with --watch).

Usage Examples:
    # One snapshot (the ID is the number in the dashboard URL, ...events/<ID>/dashboard):
    python3 scripts/eventbrite_inspect.py 2003659307927

    # Keep watching, printing a block only when something changes (check every 20 seconds, Ctrl+C to stop):
    python3 scripts/eventbrite_inspect.py 2003659307927 --watch 20

Only order ids and counts are printed, never names or emails.
"""

import argparse
import os
import sys
import time
from datetime import datetime

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import config
from core.eventbrite.client import EventbriteError, eb_get, paginate

MIN_WATCH_SECONDS = 15  # each snapshot costs at least 2 API calls, shared with the bot's own polling


def bot_seat_count(eb_event_id):
    """(bot event id, Eventbrite seats the bot has stored) for this Eventbrite event, or None when unknown."""
    try:
        from core.db.connection import fetch_one
        from core.db.reservations import eventbrite_seat_count

        row = fetch_one("SELECT id FROM events WHERE eventbrite_event_id = ?", (str(eb_event_id),))
        return (row['id'], eventbrite_seat_count(row['id'])) if row else None
    except Exception:
        return None


def fetch_snapshot(eb_event_id):
    event = eb_get(f"/events/{eb_event_id}/", params={"expand": "ticket_classes"})
    classes = [
        {
            "name": tc.get("name"),
            "total": tc.get("quantity_total"),
            "sold": int(tc.get("quantity_sold") or 0),
            "pending": tc.get("quantity_pending"),
        }
        for tc in event.get("ticket_classes") or []
    ]

    orders = []
    for order in paginate(f"/events/{eb_event_id}/orders/", {"status": "all_not_deleted", "expand": "attendees"}, "orders"):
        attendees = order.get("attendees") or []
        cancelled = sum(1 for a in attendees if a.get("cancelled"))
        refunded = sum(1 for a in attendees if a.get("refunded"))
        orders.append({
            "id": str(order.get("id")),
            "status": order.get("status"),
            "attendees": len(attendees),
            "cancelled": cancelled,
            "refunded": refunded,
            "active": sum(1 for a in attendees if not a.get("cancelled") and not a.get("refunded")),
        })

    return {
        "status": event.get("status"),
        "classes": classes,
        "sold": sum(tc["sold"] for tc in classes),
        "orders": orders,
        "active": sum(o["active"] for o in orders),
        "bot": bot_seat_count(eb_event_id),
    }


def render(snapshot):
    lines = [f"Evento: stato {snapshot['status']}"]
    for tc in snapshot["classes"]:
        pending = f", in attesa {tc['pending']}" if tc["pending"] is not None else ""
        lines.append(f"  Biglietto «{tc['name']}»: totale {tc['total']}, venduti {tc['sold']}{pending}")
    lines.append(f"Venduti (somma biglietti): {snapshot['sold']}")

    lines.append(f"Ordini ({len(snapshot['orders'])}):")
    for order in snapshot["orders"]:
        lines.append(
            f"  ordine {order['id']}: stato {order['status']}, partecipanti {order['attendees']} "
            f"(annullati {order['cancelled']}, rimborsati {order['refunded']}, attivi {order['active']})"
        )
    if not snapshot["orders"]:
        lines.append("  nessuno")

    verdict = "UGUALI" if snapshot["sold"] == snapshot["active"] else "DIVERSI"
    lines.append(f"quantity_sold {snapshot['sold']} vs partecipanti attivi {snapshot['active']} → {verdict}")
    if snapshot["bot"]:
        bot_event_id, bot_seats = snapshot["bot"]
        same = "UGUALI" if bot_seats == snapshot["sold"] else "DIVERSI"
        lines.append(f"Il bot ha registrato {bot_seats} posti Eventbrite per l'evento #{bot_event_id} "
                     f"(vs quantity_sold {snapshot['sold']} → {same})")
    return lines


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Ispeziona un evento Eventbrite: quantity_sold, ordini e partecipanti (sola lettura).",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("event_id", help="ID dell'evento su Eventbrite (il numero nell'URL della dashboard).")
    parser.add_argument("--watch", type=int, metavar="SECONDI",
                        help=f"Ripete il controllo e stampa solo quando qualcosa cambia (minimo {MIN_WATCH_SECONDS}).")
    args = parser.parse_args(argv)
    if args.watch is not None and args.watch < MIN_WATCH_SECONDS:
        parser.error(f"--watch deve essere almeno {MIN_WATCH_SECONDS} secondi (limite di chiamate API condiviso con il bot)")
    return args


def main(argv=None, sleep=time.sleep):
    args = parse_args(argv)
    if not config.EVENTBRITE_TOKEN:
        print("❌ EVENTBRITE_TOKEN non impostato nel file .env.")
        return 1

    previous = None
    try:
        while True:
            try:
                lines = render(fetch_snapshot(args.event_id))
            except EventbriteError as e:
                print(f"❌ Errore Eventbrite: {e}")
                if args.watch is None:
                    return 1
            else:
                if lines != previous:
                    print(f"\n[{datetime.now():%H:%M:%S}]")
                    print("\n".join(lines))
                    previous = lines
            if args.watch is None:
                return 0
            sleep(args.watch)
    except KeyboardInterrupt:
        print("\nInterrotto.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
