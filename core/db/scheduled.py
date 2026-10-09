"""scheduled_events: reusable event templates that admins repost on chosen weekdays or dates."""
import json

from core.db.connection import db_safe, execute, fetch_all, fetch_one
from utils.date_utils import parse_date_tuple_from_str


def _encode_days(schedule_days):
    if isinstance(schedule_days, list):
        return json.dumps(schedule_days)
    if isinstance(schedule_days, str):
        return schedule_days
    return "[]"


def _decode_days(row):
    if row is None:
        return None
    try:
        row['schedule_days'] = json.loads(row.get('schedule_days') or '[]')
    except (TypeError, ValueError):
        row['schedule_days'] = []
    return row


@db_safe()
def insert_scheduled_event(title, text, image_path=None, schedule_days=None, specific_date=None):
    return execute(
        'INSERT INTO scheduled_events (title, text, image_path, schedule_days, specific_date) VALUES (?, ?, ?, ?, ?)',
        (title or '', text or '', image_path, _encode_days(schedule_days), specific_date),
    )


@db_safe()
def get_scheduled_event(scheduled_id):
    return _decode_days(fetch_one('SELECT * FROM scheduled_events WHERE id = ?', (scheduled_id,)))


@db_safe(default=list)
def get_all_scheduled_events():
    return [_decode_days(row) for row in fetch_all('SELECT * FROM scheduled_events ORDER BY id DESC')]


@db_safe(default=False)
def update_scheduled_event_days(scheduled_id, schedule_days):
    execute('UPDATE scheduled_events SET schedule_days = ? WHERE id = ?', (_encode_days(schedule_days), scheduled_id))
    return True


@db_safe(default=False)
def update_scheduled_event_specific_date(scheduled_id, specific_date):
    execute('UPDATE scheduled_events SET specific_date = ? WHERE id = ?', (specific_date, scheduled_id))
    return True


@db_safe(default=False)
def update_scheduled_event_content(scheduled_id, text, image_path=None, title=None):
    """Replaces the template text; image and title are only overwritten when given."""
    changes = {"text": text}
    if image_path is not None:
        changes["image_path"] = image_path
    if title is not None:
        changes["title"] = title
    assignments = ", ".join(f"{column} = ?" for column in changes)
    execute(f'UPDATE scheduled_events SET {assignments} WHERE id = ?', (*changes.values(), scheduled_id))
    return True


@db_safe(default=False)
def delete_scheduled_event(scheduled_id):
    execute('DELETE FROM scheduled_events WHERE id = ?', (scheduled_id,))
    return True


@db_safe(default=list)
def get_scheduled_events_for_date(date_str, weekday_name):
    """Templates scheduled for this weekday (e.g. 'Lunedì') or whose specific_date is date_str (DD-MM-YYYY)."""
    target = parse_date_tuple_from_str(date_str)
    weekday = weekday_name.strip().lower()

    matches = []
    for ev in get_all_scheduled_events():
        days = [d.strip().lower() for d in ev.get('schedule_days', []) if isinstance(d, str)]
        if weekday in days:
            matches.append(ev)
            continue
        spec = ev.get('specific_date')
        if spec and ((target and parse_date_tuple_from_str(spec) == target) or spec.strip().startswith(date_str)):
            matches.append(ev)
    return matches
