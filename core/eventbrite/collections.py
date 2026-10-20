from core.eventbrite.client import eb_delete, eb_post

# Collections are not in Eventbrite's public API reference, but the endpoints exist (confirmed on a real account):
# POST /collections/ {name, organizer_id}, POST|DELETE /collections/{id}/events/ {event_ids: "id1,id2"}.


def create_collection(name, organizer_id):
    """Creates a collection (draft until it is published from the dashboard); returns its JSON (id, absolute_url)."""
    return eb_post("/collections/", json={"name": name, "organizer_id": organizer_id})


def add_event_to_collection(collection_id, eb_id):
    eb_post(f"/collections/{collection_id}/events/", json={"event_ids": str(eb_id)})


def remove_event_from_collection(collection_id, eb_id):
    eb_delete(f"/collections/{collection_id}/events/", json={"event_ids": str(eb_id)})
