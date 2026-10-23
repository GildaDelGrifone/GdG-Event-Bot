from datetime import datetime, timedelta, timezone

from core.eventbrite.client import eb_post
from core.eventbrite.payload import utc_string

TICKET_NAME = "Posto"
CLOSE_SALES_AFTER = timedelta(minutes=2)  # Eventbrite rejects a sales_end that is not in the future


def create_free_ticket_class(eb_id, quantity, sales_end_utc=None, closed=False, now=None):
    """Creates the single free ticket class; sales end at sales_end_utc (aware datetime). Returns the ticket class JSON.

    closed=True is for an event with no seat left: the ticket is hidden and its sales end in a couple of minutes, so
    the event page is visible but nothing can be bought (see update_ticket_capacity)."""
    ticket_class = {"name": TICKET_NAME, "free": True, "quantity_total": quantity}
    if sales_end_utc is not None:
        ticket_class["sales_end"] = utc_string(sales_end_utc)
    if closed:
        ticket_class["hidden"] = True
        ticket_class["sales_end"] = utc_string((now or datetime.now(timezone.utc)) + CLOSE_SALES_AFTER)
    return eb_post(f"/events/{eb_id}/ticket_classes/", json={"ticket_class": ticket_class})


def update_ticket_quantity(eb_id, ticket_class_id, quantity):
    return eb_post(f"/events/{eb_id}/ticket_classes/{ticket_class_id}/", json={"ticket_class": {"quantity_total": quantity}})


def update_ticket_capacity(eb_id, ticket_class_id, quantity, sold, sales_end_utc=None, now=None):
    """Sets the ticket total, or closes sales when no seat is left (quantity <= sold). Returns the ticket class JSON.

    Eventbrite refuses quantity_total=0 and a sales_end in the past, so a sold-out event keeps total = sold (Eventbrite
    shows "Sold out") and sales end in a couple of minutes; with nothing sold the ticket is hidden as well. Free seats
    again reopen the sales: total back, ticket visible, sales ending when the event does (sales_end_utc)."""
    if quantity > sold:
        ticket_class = {"quantity_total": quantity, "hidden": False}
        if sales_end_utc is not None:
            ticket_class["sales_end"] = utc_string(sales_end_utc)
    else:
        ticket_class = {"sales_end": utc_string((now or datetime.now(timezone.utc)) + CLOSE_SALES_AFTER)}
        if sold:
            ticket_class["quantity_total"] = sold
        else:
            ticket_class["hidden"] = True
    return eb_post(f"/events/{eb_id}/ticket_classes/{ticket_class_id}/", json={"ticket_class": ticket_class})
