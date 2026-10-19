from core.eventbrite.client import eb_post
from core.eventbrite.payload import utc_string

TICKET_NAME = "Posto"


def create_free_ticket_class(eb_id, quantity, sales_end_utc=None):
    """Creates the single free ticket class; sales end at sales_end_utc (aware datetime). Returns the ticket class JSON."""
    ticket_class = {"name": TICKET_NAME, "free": True, "quantity_total": quantity}
    if sales_end_utc is not None:
        ticket_class["sales_end"] = utc_string(sales_end_utc)
    return eb_post(f"/events/{eb_id}/ticket_classes/", json={"ticket_class": ticket_class})


def update_ticket_quantity(eb_id, ticket_class_id, quantity):
    return eb_post(f"/events/{eb_id}/ticket_classes/{ticket_class_id}/", json={"ticket_class": {"quantity_total": quantity}})
