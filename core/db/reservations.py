from core.db.connection import db_safe, fetch_all, fetch_one
from core.db.events import get_event
from utils.date_utils import are_events_on_same_day

# Matches a reservation by stored username or, for users without one, by display name
NAME_MATCH_SQL = (
    "(username IS NOT NULL AND LOWER(username) = LOWER(?)) "
    "OR (full_name IS NOT NULL AND LOWER(full_name) = LOWER(?))"
)


def clean_username(username):
    return (username or '').strip().lstrip('@')


def normalize_identity(username, full_name):
    """(username without @, full name), both None when blank; a "username" containing spaces is treated as a full name."""
    uname = clean_username(username) if isinstance(username, str) else ''
    fname = full_name.strip() if isinstance(full_name, str) else ''
    if uname and " " in uname and not fname:
        return None, uname
    return uname or None, fname or None


@db_safe(default=list)
def get_reservations_for_event(event_id):
    return fetch_all('SELECT * FROM reservations WHERE event_id = ? ORDER BY id ASC', (event_id,))


@db_safe()
def get_reservation(reservation_id):
    return fetch_one('SELECT * FROM reservations WHERE id = ?', (reservation_id,))


@db_safe()
def get_reservation_by_user(event_id, username=None, user_id=None):
    name = clean_username(username)
    conditions, params = [], [event_id]
    if user_id is not None:
        conditions.append('user_id = ?')
        params.append(user_id)
    if name:
        conditions.append(NAME_MATCH_SQL)
        params += [name, name]
    if not conditions:
        return None
    return fetch_one(f"SELECT * FROM reservations WHERE event_id = ? AND ({' OR '.join(conditions)})", tuple(params))


@db_safe(default=list)
def get_user_conflicting_events(event_id, user_id=None, username=None):
    """Other valid (not cancelled/discarded) events on the same day where the user holds seats."""
    target_event = get_event(event_id)
    if not target_event:
        return []

    name = clean_username(username)
    conditions, params = [], [event_id]
    if user_id is not None:
        conditions.append('reservations.user_id = ?')
        params.append(int(user_id))
    if name:
        conditions.append('(reservations.username IS NOT NULL AND LOWER(reservations.username) = LOWER(?))')
        params.append(name)
    if not conditions:
        return []

    candidates = fetch_all(
        f'''
        SELECT DISTINCT events.*
        FROM events
        JOIN reservations ON events.id = reservations.event_id
        WHERE events.id != ?
          AND events.status NOT IN ('cancelled', 'discarded')
          AND reservations.seats_booked > 0
          AND ({' OR '.join(conditions)})
        ORDER BY events.id ASC
        ''',
        tuple(params),
    )
    return [ev for ev in candidates if are_events_on_same_day(target_event, ev)]
