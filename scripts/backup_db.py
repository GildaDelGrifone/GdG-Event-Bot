#!/usr/bin/env python3
"""
Manual database backup (the bot also takes one every night at DB_BACKUP_TIME).

Usage:
    PYTHONPATH=. .venv/bin/python scripts/backup_db.py --now    # take a backup now (e.g. before a manual DB fix)
    PYTHONPATH=. .venv/bin/python scripts/backup_db.py --list   # list the stored copies

Restore (stop the bot first, the DB must not be in use):
    kubectl scale deployment/event-bot --replicas=0
    gunzip -c data/backups/bot_database_YYYY-MM-DD.db.gz > data/bot_database.db
    rm -f data/bot_database.db-wal data/bot_database.db-shm
    kubectl scale deployment/event-bot --replicas=1
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.scheduler.backup import backup_database, backups_dir, list_backups  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Back up the bot database or list the stored backups.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--now", action="store_true", help="take a backup now (same-day backup is overwritten)")
    group.add_argument("--list", action="store_true", help="list the stored backups")
    args = parser.parse_args()

    if args.now:
        path = backup_database()
        print(f"Backup saved: {path}" if path else "Backups are disabled (DB_BACKUP_DAYS=0).")
        return

    backups = list_backups()
    if not backups:
        print(f"No backups in {backups_dir()}")
        return
    for day, path in backups:
        print(f"{day:%Y-%m-%d}  {os.path.getsize(path) / 1024:7.0f} KB  {path}")


if __name__ == "__main__":
    main()
