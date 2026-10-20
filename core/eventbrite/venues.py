from core import config
from core.eventbrite.client import eb_get


def get_venue(venue_id):
    return eb_get(f"/venues/{venue_id}/")


def eventbrite_venue_ids():
    """The default venue first, then the alternatives (blank and repeated ids dropped)."""
    ids = []
    for venue_id in [config.EVENTBRITE_VENUE_ID, *config.EVENTBRITE_VENUE_ID_ALTERNATIVES]:
        if venue_id and venue_id not in ids:
            ids.append(venue_id)
    return ids
