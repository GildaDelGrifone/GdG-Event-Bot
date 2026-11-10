"""Eventbrite attendees whose booking announcements are silenced on one event (churn detection in the poller).

An attendee is identified by event + display name (`Mario R.`): the only identity stored for Eventbrite bookings."""
from core.db.connection import db_safe, execute, fetch_all, fetch_one


@db_safe(default=None)
def mute_eventbrite_name(event_id, name):
    """Silences `name` on the event; returns the mute id (the existing one if already silenced)."""
    execute("INSERT OR IGNORE INTO eventbrite_mutes (event_id, name) VALUES (?, ?)", (event_id, name))
    row = fetch_one("SELECT id FROM eventbrite_mutes WHERE event_id = ? AND name = ?", (event_id, name))
    return row['id'] if row else None


@db_safe(default=list)
def get_eventbrite_mutes(event_id):
    return fetch_all("SELECT * FROM eventbrite_mutes WHERE event_id = ? ORDER BY id", (event_id,))


@db_safe(default=None)
def get_eventbrite_mute(mute_id):
    return fetch_one("SELECT * FROM eventbrite_mutes WHERE id = ?", (mute_id,))


@db_safe(default=False)
def unmute_eventbrite(mute_id):
    """Lifts a silencing; False when it was already gone."""
    row = fetch_one("SELECT id FROM eventbrite_mutes WHERE id = ?", (mute_id,))
    if not row:
        return False
    execute("DELETE FROM eventbrite_mutes WHERE id = ?", (mute_id,))
    return True
