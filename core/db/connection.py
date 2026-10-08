import functools
import logging
import sqlite3
from contextlib import contextmanager

from core import config

logger = logging.getLogger(__name__)


def get_connection():
    """Raw sqlite3 connection to config.DB_PATH (read at call time so tests/scripts can redirect it)."""
    return sqlite3.connect(config.DB_PATH)


@contextmanager
def transaction():
    """Cursor with dict-like rows; commits on success, rolls back on error, and always closes the connection."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn.cursor()
    finally:
        conn.close()


def fetch_one(sql, params=()):
    with transaction() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def fetch_all(sql, params=()):
    with transaction() as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def execute(sql, params=()):
    """Runs one write statement and returns the new row id (for INSERTs)."""
    with transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def execute_many(sql, seq_of_params):
    with transaction() as cur:
        cur.executemany(sql, seq_of_params)


def db_safe(default=None):
    """Logs and swallows DB errors so callers get `default` (called when callable, e.g. `list` for a fresh [])."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                logger.error(f"DB error in {fn.__name__}: {e}")
                return default() if callable(default) else default
        return wrapper
    return decorator
