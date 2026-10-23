from core.db.connection import db_safe, get_connection, transaction

TABLES = (
    '''
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        date TEXT,
        normalized_date TEXT,
        system TEXT,
        host TEXT,
        seats TEXT,
        booked_seats INTEGER DEFAULT 0,
        max_seats INTEGER,
        description TEXT,
        extra_info TEXT,
        original_text TEXT,
        image_path TEXT,
        status TEXT DEFAULT 'pending',
        is_recap INTEGER DEFAULT 0,
        message_link TEXT,
        telegram_message_id INTEGER,
        discussion_message_id INTEGER,
        discussion_chat_id TEXT,
        wp_post_id INTEGER,
        wp_post_url TEXT,
        is_roleplay INTEGER DEFAULT 0,
        admin_message_id INTEGER,
        eventbrite_event_id TEXT,
        eventbrite_url TEXT,
        eventbrite_ticket_class_id TEXT,
        eventbrite_status TEXT,
        eventbrite_quantity_total INTEGER,
        eventbrite_content_version INTEGER DEFAULT 0,
        eventbrite_synced_at TEXT,
        eventbrite_venue_id TEXT
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER,
        user_id INTEGER,
        username TEXT,
        seats_booked INTEGER DEFAULT 0,
        full_name TEXT,
        source TEXT DEFAULT 'telegram',
        eventbrite_order_id TEXT
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS scheduled_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        text TEXT,
        image_path TEXT,
        schedule_days TEXT DEFAULT '[]',
        specific_date TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        advance_days INTEGER DEFAULT 0
    )
    ''',
)

# Columns added after the first release; ALTERed into older databases at startup
COLUMN_MIGRATIONS = {
    "events": {
        "extra_info": "TEXT",
        "discussion_message_id": "INTEGER",
        "discussion_chat_id": "TEXT",
        "is_roleplay": "INTEGER DEFAULT 0",
        "admin_message_id": "INTEGER",
        "eventbrite_event_id": "TEXT",
        "eventbrite_url": "TEXT",
        "eventbrite_ticket_class_id": "TEXT",
        "eventbrite_status": "TEXT",
        "eventbrite_quantity_total": "INTEGER",
        "eventbrite_content_version": "INTEGER DEFAULT 0",
        "eventbrite_synced_at": "TEXT",
        "eventbrite_venue_id": "TEXT",
    },
    "scheduled_events": {
        "advance_days": "INTEGER DEFAULT 0",
    },
    "reservations": {
        "full_name": "TEXT",
        "source": "TEXT DEFAULT 'telegram'",
        "eventbrite_order_id": "TEXT",
    },
}

# Applied after the migrations, so they can reference migrated columns
INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_res_eb_order ON reservations(event_id, eventbrite_order_id) "
    "WHERE eventbrite_order_id IS NOT NULL",
)

# Non-additive changes (renames, data rewrites, ...): {version: (sql, ...)}, run once, in order, on databases whose
# PRAGMA user_version is lower. Add an entry and bump SCHEMA_VERSION to its key.
VERSIONED_MIGRATIONS = {}
SCHEMA_VERSION = 1


def _enable_wal():
    """Write-ahead logging lets the Eventbrite poller and the handlers read while the other writes (persists in the file)."""
    conn = get_connection()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    finally:
        conn.close()


@db_safe()
def init_db():
    _enable_wal()
    with transaction() as cur:
        for ddl in TABLES:
            cur.execute(ddl)
        for table, columns in COLUMN_MIGRATIONS.items():
            cur.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in cur.fetchall()}
            for column, declaration in columns.items():
                if column not in existing:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
        for ddl in INDEXES:
            cur.execute(ddl)
        cur.execute("PRAGMA user_version")
        current = cur.fetchone()[0]
        for version in sorted(v for v in VERSIONED_MIGRATIONS if current < v <= SCHEMA_VERSION):
            for sql in VERSIONED_MIGRATIONS[version]:
                cur.execute(sql)
        if current < SCHEMA_VERSION:
            cur.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")
