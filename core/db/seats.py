"""Seat bookings: every change to reservations keeps events.booked_seats and events.seats in sync."""
from core.db.connection import db_safe, transaction
from core.db.reservations import NAME_MATCH_SQL, clean_username, normalize_identity

EVENT_NOT_FOUND = "Evento non trovato."
EVENT_CANCELLED = "Evento annullato."


def _load_seat_state(cur, event_id, cancelled_message=EVENT_CANCELLED):
    """Returns (event_row, None) or (None, error_message); cancelled events are rejected unless cancelled_message is None."""
    cur.execute('SELECT booked_seats, max_seats, status FROM events WHERE id = ?', (event_id,))
    ev = cur.fetchone()
    if not ev:
        return None, EVENT_NOT_FOUND
    if cancelled_message and ev['status'] == 'cancelled':
        return None, cancelled_message
    return ev, None


def _booked(ev):
    return int(ev['booked_seats'] or 0)


def _capacity(ev):
    return None if ev['max_seats'] is None else int(ev['max_seats'])


def _set_booked_seats(cur, event_id, ev, new_booked):
    new_booked = max(0, new_booked)
    capacity = _capacity(ev)
    if capacity is None:
        cur.execute('UPDATE events SET booked_seats = ? WHERE id = ?', (new_booked, event_id))
    else:
        cur.execute(
            'UPDATE events SET booked_seats = ?, seats = ? WHERE id = ?',
            (new_booked, f"{max(0, capacity - new_booked)}/{capacity}", event_id),
        )


def _decrement_or_delete(cur, reservation_id, current_seats, amount=1):
    if current_seats <= amount:
        cur.execute('DELETE FROM reservations WHERE id = ?', (reservation_id,))
    else:
        cur.execute('UPDATE reservations SET seats_booked = seats_booked - ? WHERE id = ?', (amount, reservation_id))


@db_safe(default=(False, "Errore durante la prenotazione."))
def book_seat(event_id, user_id, username=None, full_name=None):
    with transaction() as cur:
        ev, error = _load_seat_state(cur, event_id)
        if error:
            return False, error
        booked, capacity = _booked(ev), _capacity(ev)
        if capacity is not None and booked >= capacity:
            return False, "Nessun posto disponibile."

        uname, fname = normalize_identity(username, full_name)
        # Admin-added reservations have no user_id yet; claim them by username
        cur.execute(
            'SELECT id, username, full_name FROM reservations WHERE event_id = ? '
            'AND (user_id = ? OR (user_id IS NULL AND username IS NOT NULL AND LOWER(username) = LOWER(?)))',
            (event_id, user_id, uname),
        )
        res = cur.fetchone()
        if res:
            cur.execute(
                'UPDATE reservations SET seats_booked = seats_booked + 1, username = ?, full_name = ?, user_id = ? WHERE id = ?',
                (uname if uname is not None else res['username'], fname if fname is not None else res['full_name'], user_id, res['id']),
            )
        else:
            cur.execute(
                'INSERT INTO reservations (event_id, user_id, username, full_name, seats_booked) VALUES (?, ?, ?, ?, 1)',
                (event_id, user_id, uname, fname),
            )
        _set_booked_seats(cur, event_id, ev, booked + 1)
    return True, "Prenotazione aggiunta."


@db_safe(default=(False, "Errore durante la rimozione della prenotazione."))
def unbook_seat(event_id, user_id, username=None):
    with transaction() as cur:
        ev, error = _load_seat_state(cur, event_id)
        if error:
            return False, error

        name = clean_username(username)
        cur.execute(
            "SELECT id, seats_booked FROM reservations WHERE event_id = ? AND (user_id = ? "
            "OR (LOWER(username) = LOWER(?) AND ? != '') OR (full_name IS NOT NULL AND LOWER(full_name) = LOWER(?) AND ? != ''))",
            (event_id, user_id, name, name, name, name),
        )
        res = cur.fetchone()
        if not res or res['seats_booked'] <= 0:
            return False, "Non hai posti prenotati da liberare."

        _decrement_or_delete(cur, res['id'], res['seats_booked'])
        _set_booked_seats(cur, event_id, ev, _booked(ev) - 1)
    return True, "Prenotazione rimossa."


@db_safe(default=(False, "Errore durante l'aggiunta del posto."))
def admin_add_seat(event_id, reservation_id):
    with transaction() as cur:
        ev, error = _load_seat_state(cur, event_id)
        if error:
            return False, error
        booked, capacity = _booked(ev), _capacity(ev)
        if capacity is not None and booked >= capacity:
            return False, "Capienza massima raggiunta!"

        cur.execute('SELECT id, username FROM reservations WHERE id = ? AND event_id = ?', (reservation_id, event_id))
        res = cur.fetchone()
        if not res:
            return False, "Prenotazione non trovata."

        cur.execute('UPDATE reservations SET seats_booked = seats_booked + 1 WHERE id = ?', (reservation_id,))
        _set_booked_seats(cur, event_id, ev, booked + 1)
    return True, f"Aggiunto 1 posto a {res['username'] or 'Utente'}."


@db_safe(default=(False, "Errore durante la rimozione del posto."))
def admin_remove_seat(event_id, reservation_id):
    with transaction() as cur:
        ev, error = _load_seat_state(cur, event_id, cancelled_message=None)
        if error:
            return False, error

        cur.execute('SELECT id, seats_booked, username FROM reservations WHERE id = ? AND event_id = ?', (reservation_id, event_id))
        res = cur.fetchone()
        if not res:
            return False, "Prenotazione non trovata."

        _decrement_or_delete(cur, reservation_id, res['seats_booked'])
        _set_booked_seats(cur, event_id, ev, _booked(ev) - 1)
    return True, f"Rimosso 1 posto a {res['username'] or 'Utente'}."


@db_safe(default=(False, "Errore durante l'aggiunta dell'iscritto."))
def admin_add_subscriber(event_id, username, seats=1, user_id=None, full_name=None):
    seats = int(seats)
    if seats <= 0:
        return False, "Il numero di posti deve essere almeno 1."
    uname, fname = normalize_identity(username, full_name)
    if not uname and not fname and user_id is None:
        return False, "Specificare un username o un user_id valido."

    with transaction() as cur:
        ev, error = _load_seat_state(cur, event_id, cancelled_message="Evento annullato. Riattivalo prima di aggiungere iscritti.")
        if error:
            return False, error
        booked, capacity = _booked(ev), _capacity(ev)
        if capacity is not None and booked + seats > capacity:
            return False, f"Capienza superata! Posti disponibili: {max(0, capacity - booked)}/{capacity}."

        cur.execute(
            f'SELECT id, username, full_name FROM reservations WHERE event_id = ? AND (user_id = ? OR {NAME_MATCH_SQL})',
            (event_id, user_id, uname, fname or uname),
        )
        res = cur.fetchone()
        if res:
            cur.execute(
                'UPDATE reservations SET seats_booked = seats_booked + ?, username = ?, full_name = ? WHERE id = ?',
                (seats, uname if uname is not None else res['username'], fname if fname is not None else res['full_name'], res['id']),
            )
        else:
            cur.execute(
                'INSERT INTO reservations (event_id, user_id, username, full_name, seats_booked) VALUES (?, ?, ?, ?, ?)',
                (event_id, user_id, uname, fname, seats),
            )
        _set_booked_seats(cur, event_id, ev, booked + seats)

    display_name = f"@{uname}" if uname else fname or f"ID:{user_id}"
    return True, f"Iscritto {display_name} registrato con successo ({seats} posto/i)."


@db_safe(default=(False, "Errore durante la rimozione dell'iscritto."))
def admin_remove_subscriber(event_id, username, seats=None):
    name = clean_username(username)
    if not name:
        return False, "Specificare un username valido."

    with transaction() as cur:
        ev, error = _load_seat_state(cur, event_id, cancelled_message=None)
        if error:
            return False, error

        cur.execute(
            f'SELECT id, seats_booked, username, full_name FROM reservations WHERE event_id = ? AND ({NAME_MATCH_SQL})',
            (event_id, name, name),
        )
        res = cur.fetchone()
        if not res:
            return False, f"Nessun iscritto trovato con username @{name}."

        current_seats = res['seats_booked']
        seats_to_remove = current_seats if seats is None or int(seats) >= current_seats else int(seats)
        _decrement_or_delete(cur, res['id'], current_seats, seats_to_remove)
        _set_booked_seats(cur, event_id, ev, _booked(ev) - seats_to_remove)

    display_name = f"@{res['username']}" if res['username'] else res['full_name'] or f"@{name}"
    return True, f"Rimossi {seats_to_remove} posto/i per {display_name}."
