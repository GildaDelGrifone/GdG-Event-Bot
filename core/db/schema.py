from core.db.connection import db_safe, transaction

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
        admin_message_id INTEGER
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER,
        user_id INTEGER,
        username TEXT,
        seats_booked INTEGER DEFAULT 0,
        full_name TEXT
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
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    },
    "reservations": {
        "full_name": "TEXT",
    },
}


@db_safe()
def init_db():
    with transaction() as cur:
        for ddl in TABLES:
            cur.execute(ddl)
        for table, columns in COLUMN_MIGRATIONS.items():
            cur.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in cur.fetchall()}
            for column, declaration in columns.items():
                if column not in existing:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
