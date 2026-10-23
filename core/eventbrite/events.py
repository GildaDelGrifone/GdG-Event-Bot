from core import config
from core.eventbrite.client import eb_delete, eb_get, eb_post


def create_event(payload):
    """Creates a draft event; returns the event JSON (including id and url)."""
    return eb_post(f"/organizations/{config.EVENTBRITE_ORGANIZATION_ID}/events/", json={"event": payload})


def update_event(eb_id, payload):
    return eb_post(f"/events/{eb_id}/", json={"event": payload})


def get_event(eb_id):
    """Event JSON with ticket_classes expanded (status, quantity_sold)."""
    return eb_get(f"/events/{eb_id}/", params={"expand": "ticket_classes"})


def publish_event(eb_id):
    return bool(eb_post(f"/events/{eb_id}/publish/").get("published"))


def unpublish_event(eb_id):
    """Works only while the event has no orders; raises EventbriteError otherwise."""
    return bool(eb_post(f"/events/{eb_id}/unpublish/").get("unpublished"))


def cancel_event(eb_id):
    """Works only while the event has no orders, and cannot be undone; raises EventbriteError otherwise."""
    return bool(eb_post(f"/events/{eb_id}/cancel/").get("canceled"))


def delete_eventbrite_event(eb_id):
    """Deletes the event; like cancel it works only while the event has no orders and raises EventbriteError otherwise."""
    eb_delete(f"/events/{eb_id}/")
    return True


def set_description(eb_id, modules, version):
    """Writes the listing page at `version` (the last version + 1, starting at 1) and returns it. Always send all modules."""
    eb_post(
        f"/events/{eb_id}/structured_content/{version}/",
        json={"modules": modules, "publish": True, "purpose": "listing"},
    )
    return version
