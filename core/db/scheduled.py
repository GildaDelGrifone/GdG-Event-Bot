"""scheduled_events: reusable event templates that admins repost on chosen weekdays or dates."""
import json
from datetime import date, timedelta

from core.db.connection import db_safe, execute, fetch_all, fetch_one
from utils.date_utils import DAYS_IT, parse_date_tuple_from_str

MAX_ADVANCE_DAYS = 30


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


def clamp_advance_days(days):
    try:
        return max(0, min(MAX_ADVANCE_DAYS, int(days or 0)))
    except (TypeError, ValueError):
        return 0


@db_safe()
def insert_scheduled_event(title, text, image_path=None, schedule_days=None, specific_date=None, advance_days=0):
    return execute(
        'INSERT INTO scheduled_events (title, text, image_path, schedule_days, specific_date, advance_days) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (title or '', text or '', image_path, _encode_days(schedule_days), specific_date, clamp_advance_days(advance_days)),
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
def update_scheduled_event_advance_days(scheduled_id, days):
    execute('UPDATE scheduled_events SET advance_days = ? WHERE id = ?', (clamp_advance_days(days), scheduled_id))
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


def _matches_date(ev, date_str, weekday_name):
    target = parse_date_tuple_from_str(date_str)
    weekday = weekday_name.strip().lower()
    days = [d.strip().lower() for d in ev.get('schedule_days', []) if isinstance(d, str)]
    if weekday in days:
        return True
    spec = ev.get('specific_date')
    return bool(spec and ((target and parse_date_tuple_from_str(spec) == target) or spec.strip().startswith(date_str)))


def _matches_day(ev, day):
    return _matches_date(ev, day.strftime("%d-%m-%Y"), DAYS_IT[day.weekday()])


@db_safe(default=list)
def get_scheduled_events_for_date(date_str, weekday_name):
    """Templates scheduled for this weekday (e.g. 'Lunedì') or whose specific_date is date_str (DD-MM-YYYY)."""
    return [ev for ev in get_all_scheduled_events() if _matches_date(ev, date_str, weekday_name)]


@db_safe(default=list)
def get_scheduled_events_due(today: date):
    """(template, event_date) for the templates whose event falls advance_days after today."""
    due = []
    for ev in get_all_scheduled_events():
        event_date = today + timedelta(days=clamp_advance_days(ev.get('advance_days')))
        if _matches_day(ev, event_date):
            due.append((ev, event_date))
    return due


def next_scheduled_occurrence(ev, today: date):
    """Nearest date on or after today (today included) on which the template is scheduled, or None."""
    candidates = [today + timedelta(days=offset) for offset in range(7)]
    spec = parse_date_tuple_from_str(ev.get('specific_date') or '')
    if spec and date(*spec) >= today:
        candidates.append(date(*spec))
    matching = [day for day in candidates if _matches_day(ev, day)]
    return min(matching) if matching else None
