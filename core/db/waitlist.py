"""Waitlist of a full event: Telegram users queue with the full-event button and get the next free seat automatically."""
from core.db.connection import db_safe, fetch_all, fetch_one, transaction
from core.db.seats import _add_telegram_seat, _booked, _capacity, _load_seat_state


def _position(cur, event_id, user_id):
    cur.execute('SELECT id FROM waitlist WHERE event_id = ? AND user_id = ?', (event_id, user_id))
    row = cur.fetchone()
    if not row:
        return None
    cur.execute('SELECT COUNT(*) FROM waitlist WHERE event_id = ? AND id <= ?', (event_id, row['id']))
    return cur.fetchone()[0]


@db_safe(default=(None, False))
def join_waitlist(event_id, user_id, username=None, full_name=None):
    """Queues the user for the event's next free seat. Returns (position, newly_added); (None, False) if not possible.

    One entry per user and event; a user who already holds a seat can queue for one more.
    """
    with transaction() as cur:
        ev, error = _load_seat_state(cur, event_id)
        if error or ev['status'] != 'approved' or _capacity(ev) is None:
            return None, False
        existing = _position(cur, event_id, user_id)
        if existing:
            return existing, False
        cur.execute(
            'INSERT INTO waitlist (event_id, user_id, username, full_name) VALUES (?, ?, ?, ?)',
            (event_id, user_id, username, full_name),
        )
        return _position(cur, event_id, user_id), True


@db_safe(default=False)
def leave_waitlist(event_id, user_id):
    with transaction() as cur:
        cur.execute('DELETE FROM waitlist WHERE event_id = ? AND user_id = ?', (event_id, user_id))
        return cur.rowcount > 0


@db_safe(default=None)
def waitlist_position(event_id, user_id):
    with transaction() as cur:
        return _position(cur, event_id, user_id)


@db_safe(default=list)
def get_waitlist(event_id):
    """The queue of an event, first in line first."""
    return fetch_all('SELECT * FROM waitlist WHERE event_id = ? ORDER BY id', (event_id,))


@db_safe(default=0)
def waitlist_count(event_id):
    return fetch_one('SELECT COUNT(*) AS n FROM waitlist WHERE event_id = ?', (event_id,))['n']


@db_safe(default=list)
def promote_waitlist(event_id):
    """Gives the free seats of an approved event to the people waiting, in order, in one transaction.

    Returns the promoted waitlist rows (user_id, username, full_name), first promoted first.
    """
    promoted = []
    with transaction() as cur:
        while True:
            ev, error = _load_seat_state(cur, event_id)
            if error or ev['status'] != 'approved':
                break
            capacity = _capacity(ev)
            if capacity is None or _booked(ev) >= capacity:
                break
            cur.execute('SELECT * FROM waitlist WHERE event_id = ? ORDER BY id LIMIT 1', (event_id,))
            entry = cur.fetchone()
            if not entry:
                break
            _add_telegram_seat(cur, event_id, ev, entry['user_id'], entry['username'], entry['full_name'])
            cur.execute('DELETE FROM waitlist WHERE id = ?', (entry['id'],))
            promoted.append(dict(entry))
    return promoted


@db_safe(default=0)
def clear_waitlist(event_id):
    with transaction() as cur:
        cur.execute('DELETE FROM waitlist WHERE event_id = ?', (event_id,))
        return cur.rowcount
