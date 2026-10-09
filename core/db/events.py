from datetime import datetime

from core.db.connection import db_safe, execute, execute_many, fetch_all, fetch_one, transaction
from utils.date_utils import event_date_tuple, parse_date_tuple_from_str

EDITABLE_EVENT_FIELDS = frozenset({
    'title', 'date', 'normalized_date', 'system', 'host',
    'seats', 'booked_seats', 'max_seats', 'description', 'extra_info',
    'discussion_message_id', 'discussion_chat_id', 'image_path', 'is_roleplay',
    'admin_message_id',
})
_MESSAGE_ID_COLUMNS = frozenset({'telegram_message_id', 'discussion_message_id', 'admin_message_id'})
_TRUTHY_ROLEPLAY = (True, 1, '1', 'true', 'True')


@db_safe()
def insert_event(event_data, image_path, original_text, message_link=None, telegram_message_id=None):
    if message_link is None:
        message_link = event_data.get('message_link')
    if telegram_message_id is None:
        telegram_message_id = event_data.get('telegram_message_id')

    return execute(
        '''
        INSERT INTO events (title, date, normalized_date, system, host, seats, booked_seats, max_seats, description,
                            extra_info, original_text, image_path, status, is_recap, message_link, telegram_message_id, is_roleplay)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
        ''',
        (
            event_data.get('title', ''),
            event_data.get('date', ''),
            event_data.get('normalized_date', ''),
            event_data.get('system', ''),
            event_data.get('host', ''),
            event_data.get('seats', ''),
            event_data.get('booked_seats', 0),
            event_data.get('max_seats', None),
            event_data.get('description', ''),
            event_data.get('extra_info', ''),
            original_text,
            image_path,
            message_link,
            telegram_message_id,
            1 if event_data.get('is_roleplay') in _TRUTHY_ROLEPLAY else 0,
        ),
    )


@db_safe()
def update_event_status(event_id, status):
    execute('UPDATE events SET status = ? WHERE id = ?', (status, event_id))


@db_safe(default=False)
def update_event_field(event_id, field, value):
    if field not in EDITABLE_EVENT_FIELDS:
        return False
    execute(f'UPDATE events SET {field} = ? WHERE id = ?', (value, event_id))
    return True


@db_safe(default=False)
def delete_event(event_id):
    with transaction() as cur:
        cur.execute('DELETE FROM reservations WHERE event_id = ?', (event_id,))
        cur.execute('DELETE FROM events WHERE id = ?', (event_id,))
    return True


@db_safe()
def get_event(event_id):
    return fetch_one('SELECT * FROM events WHERE id = ?', (event_id,))


def _get_event_by_message(column, message_id):
    if column not in _MESSAGE_ID_COLUMNS:
        raise ValueError(f"Unsupported lookup column: {column}")
    return fetch_one(f'SELECT * FROM events WHERE {column} = ?', (message_id,))


@db_safe()
def get_event_by_telegram_message_id(message_id):
    return _get_event_by_message('telegram_message_id', message_id)


@db_safe()
def get_event_by_discussion_message_id(message_id):
    return _get_event_by_message('discussion_message_id', message_id)


@db_safe()
def get_event_by_admin_message_id(message_id):
    return _get_event_by_message('admin_message_id', message_id)


@db_safe(default=list)
def get_pending_events_for_recap(date_str):
    """All approved and cancelled events whose normalized_date (DD-MM-YYYY) equals date_str."""
    return fetch_all(
        "SELECT * FROM events WHERE status IN ('approved', 'cancelled') AND normalized_date = ?", (date_str,)
    )


@db_safe()
def mark_events_as_recap(event_ids):
    execute_many('UPDATE events SET is_recap = 1 WHERE id = ?', [(eid,) for eid in event_ids])


@db_safe()
def update_events_wp_info(event_ids, post_id, post_url):
    execute_many(
        'UPDATE events SET wp_post_id = ?, wp_post_url = ? WHERE id = ?',
        [(post_id, post_url, eid) for eid in event_ids],
    )


@db_safe()
def update_telegram_message_info(event_id, message_id, message_link):
    execute('UPDATE events SET telegram_message_id = ?, message_link = ? WHERE id = ?', (message_id, message_link, event_id))


@db_safe()
def update_discussion_message_info(event_id, message_id, chat_id=None):
    if chat_id is None:
        execute('UPDATE events SET discussion_message_id = ? WHERE id = ?', (message_id, event_id))
    else:
        execute(
            'UPDATE events SET discussion_message_id = ?, discussion_chat_id = ? WHERE id = ?',
            (message_id, str(chat_id), event_id),
        )


@db_safe(default=list)
def get_approved_events_for_date(date_str):
    target = parse_date_tuple_from_str(date_str)
    if not target:
        return []
    rows = fetch_all("SELECT * FROM events WHERE status = 'approved'")
    return [
        row for row in rows
        if parse_date_tuple_from_str(row.get('normalized_date')) == target
        or parse_date_tuple_from_str(row.get('date')) == target
    ]


@db_safe(default=list)
def get_upcoming_events(include_today=True):
    """Approved and pending events from today (or tomorrow) on, chronologically; undated events last."""
    now = datetime.now()
    today = (now.year, now.month, now.day)

    dated, undated = [], []
    for ev in fetch_all("SELECT * FROM events WHERE status IN ('approved', 'pending')"):
        day = event_date_tuple(ev)
        if not day:
            undated.append(ev)
        elif day > today or (include_today and day == today):
            dated.append((day, ev))

    dated.sort(key=lambda item: (item[0], item[1].get('id', 0)))
    return [ev for _, ev in dated] + undated
