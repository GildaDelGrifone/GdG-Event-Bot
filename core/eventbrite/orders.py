from core.eventbrite.client import eb_post, paginate
from core.eventbrite.payload import attendee_display_name


def fetch_active_orders(eb_id):
    """{order_id: (display_name, seat_count)} counting attendees that are neither cancelled nor refunded.
    Orders left with no seats are skipped. Only names are kept, never emails."""
    orders = {}
    params = {"status": "all_not_deleted", "expand": "attendees"}
    for order in paginate(f"/events/{eb_id}/orders/", params, "orders"):
        active = [a for a in order.get("attendees") or [] if not a.get("cancelled") and not a.get("refunded")]
        if not active:
            continue
        profile = active[0].get("profile") or order
        orders[str(order["id"])] = (attendee_display_name(profile), len(active))
    return orders


def refund_order(order_id):
    """Fully refunds an order (Eventbrite has no cancel-order call) and emails the attendee. Raises EventbriteError on refusal."""
    return eb_post(f"/orders/{order_id}/refunds/", json={"send_refund_email": True})
