"""bot_settings: a small key/value store for runtime switches that must survive a restart (values stored as JSON)."""
import json

from core.db.connection import db_safe, execute, fetch_one


@db_safe(default=(False, None))
def _read(key):
    row = fetch_one("SELECT value FROM bot_settings WHERE key = ?", (key,))
    return (False, None) if row is None else (True, json.loads(row['value']))


def get_setting(key, default=None):
    """The stored value of `key`, or `default` when it was never set (or the DB cannot be read)."""
    found, value = _read(key)
    return value if found else default


@db_safe(default=False)
def set_setting(key, value):
    execute(
        "INSERT INTO bot_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )
    return True
