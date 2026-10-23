"""Pure functions turning bot events into Eventbrite payloads (no HTTP)."""
import html
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core import config
from utils.date_utils import extract_event_datetime
from utils.templates.common import ASSOCIATION_ADDRESS

NAME_MAX_LENGTH = 75
SUMMARY_MAX_LENGTH = 140
CANCELLED_PREFIX = "[ANNULLATO] "
DEFAULT_ATTENDEE_NAME = "Partecipante Eventbrite"
_TRUTHY_ROLEPLAY = (True, 1, '1', 'true', 'True')


def utc_string(moment):
    """'YYYY-MM-DDThh:mm:ssZ' for an aware datetime."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def event_start_end(event, now=None):
    """(start, end) as aware UTC datetimes. Raises ValueError('data mancante' / 'data nel passato') without a usable future start."""
    local_start = extract_event_datetime(event, config.EVENTBRITE_DEFAULT_START_TIME)
    if local_start is None:
        raise ValueError("data mancante")
    start = local_start.replace(tzinfo=ZoneInfo(config.EVENTBRITE_TIMEZONE)).astimezone(timezone.utc)
    if start <= (now or datetime.now(timezone.utc)):
        raise ValueError("data nel passato")
    return start, start + timedelta(hours=config.EVENTBRITE_EVENT_DURATION_HOURS)


def _truncate(text, limit):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def event_name(event):
    """Plain-text name (cancelled events get the [ANNULLATO] prefix), cut to Eventbrite's length limit."""
    name = (event.get("title") or "Evento").strip() or "Evento"
    if event.get("status") == "cancelled":
        name = CANCELLED_PREFIX + name
    return _truncate(name, NAME_MAX_LENGTH)


def event_summary(event):
    return _truncate(event.get("description") or event.get("system") or "", SUMMARY_MAX_LENGTH)


def _timestamp(moment):
    return {"timezone": config.EVENTBRITE_TIMEZONE, "utc": utc_string(moment)}


def event_payload(event, include_dates=True):
    """The inner `event` object for create/update. include_dates=False leaves start/end untouched (e.g. a date moved into the past)."""
    payload = {
        "name": {"html": html.escape(event_name(event))},
        "summary": event_summary(event),
        "currency": config.EVENTBRITE_CURRENCY,
        "listed": bool(config.EVENTBRITE_LISTED),
        "shareable": True,
        "show_remaining": True,
    }
    # Only the venue the event was published with: events without one (published before venues were stored) are
    # never moved by an update, whatever EVENTBRITE_VENUE_ID is now
    if event.get("eventbrite_venue_id"):
        payload["venue_id"] = event["eventbrite_venue_id"]
    if config.EVENTBRITE_ORGANIZER_ID:
        payload["organizer_id"] = config.EVENTBRITE_ORGANIZER_ID
    if include_dates:
        start, end = event_start_end(event)
        payload["start"] = _timestamp(start)
        payload["end"] = _timestamp(end)
    return payload


def _paragraphs(text):
    return [f"<p>{html.escape(line.strip())}</p>" for line in (text or "").splitlines() if line.strip()]


def description_modules(event):
    """One structured-content text module; the HTML uses only p, b, em, ul, li and a."""
    parts = []
    if (event.get("system") or "").strip():
        parts.append(f"<p><b>Sistema:</b> {html.escape(event['system'].strip())}</p>")
    if (event.get("host") or "").strip():
        label = "Master" if event.get("is_roleplay") in _TRUTHY_ROLEPLAY else "Host"
        parts.append(f"<p><b>{label}:</b> {html.escape(event['host'].strip())}</p>")
    if event.get("max_seats"):  # unlimited (NULL) and 0/0 have no number worth showing
        parts.append(f"<p><b>Posti totali:</b> {int(event['max_seats'])}</p>")
    if (event.get("extra_info") or "").strip():
        parts.append("<p><b>Dettagli:</b></p>")
        parts.extend(_paragraphs(event["extra_info"]))
    parts.extend(_paragraphs(event.get("description")))
    parts.append(f"<p><em>{html.escape(ASSOCIATION_ADDRESS)}</em></p>")
    if event.get("message_link"):
        parts.append(f'<p><a href="{html.escape(event["message_link"], quote=True)}">Evento su Telegram</a></p>')
    return [{
        "type": "text",
        "data": {"body": {"type": "text", "text": "".join(parts), "alignment": "left"}},
    }]


def ticket_quantity(event, eb_seats, unlimited_capacity):
    """quantity_total so that (quantity - Eventbrite sold) equals the seats still free on Telegram."""
    if event.get("status") == "cancelled":
        return eb_seats
    telegram_booked = max(0, int(event.get("booked_seats") or 0) - eb_seats)
    max_seats = event.get("max_seats")
    capacity = unlimited_capacity if max_seats is None else int(max_seats)
    return max(eb_seats, capacity - telegram_booked)


def attendee_display_name(profile):
    """'Mario R.' (first name + last initial), falling back to the full name, then a generic label."""
    profile = profile or {}
    first = (profile.get("first_name") or "").strip()
    last = (profile.get("last_name") or "").strip()
    if first and last:
        return f"{first} {last[0].upper()}."
    if first:
        return first
    return (profile.get("name") or "").strip() or DEFAULT_ATTENDEE_NAME


def dashboard_url(eb_event_id):
    return f"https://www.eventbrite.com/events/{eb_event_id}/dashboard/?eid={eb_event_id}"


def order_url(order_id):
    """The organizer's page for one order (details, plus the "Cancel order" action)."""
    return f"https://www.eventbrite.com/organizations/orders/{order_id}"


def order_cancel_url(eb_event_id, order_id):
    """Eventbrite's "Cancel order" confirmation page; the API has no call to cancel an order."""
    return f"https://www.eventbrite.com/order-cancel?eid={eb_event_id}&oid={order_id}&aid="
