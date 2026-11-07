#!/usr/bin/env python3
"""
Manual database backup (the bot also takes one every night at DB_BACKUP_TIME).

Usage:
    PYTHONPATH=. .venv/bin/python scripts/backup_db.py --now    # take a backup now (e.g. before a manual DB fix)
    PYTHONPATH=. .venv/bin/python scripts/backup_db.py --list   # list the stored copies (local, and R2 if configured)
    PYTHONPATH=. .venv/bin/python scripts/backup_db.py --fetch YYYY-MM-DD   # download a copy from R2 into data/backups/

With DB_BACKUP_R2_BUCKET set, every backup is also copied to that private R2 bucket under backups/.
If the disk is lost, --fetch the copy you want first, then restore it as below.

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

from core.scheduler.backup import (  # noqa: E402
    REMOTE_PREFIX, backup_database, backups_dir, list_backups, list_remote_backups, offsite_bucket, upload_backup_offsite,
)
from core.astro import download_file  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Back up the bot database or list the stored backups.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--now", action="store_true", help="take a backup now (same-day backup is overwritten)")
    group.add_argument("--list", action="store_true", help="list the stored backups")
    group.add_argument("--fetch", metavar="YYYY-MM-DD", help="download that day's copy from the R2 bucket")
    args = parser.parse_args()

    if args.now:
        path = backup_database()
        if not path:
            print("Backups are disabled (DB_BACKUP_DAYS=0).")
            return
        print(f"Backup saved: {path}")
        kept = upload_backup_offsite(path)
        if kept is not None:
            print(f"Copied to R2 bucket {offsite_bucket()} ({kept} remote copies kept).")
        return

    if args.fetch:
        bucket = offsite_bucket()
        if not bucket:
            sys.exit("DB_BACKUP_R2_BUCKET is not set.")
        name = f"bot_database_{args.fetch}.db.gz"
        os.makedirs(backups_dir(), exist_ok=True)
        target = os.path.join(backups_dir(), name)
        download_file(REMOTE_PREFIX + name, target, bucket)
        print(f"Downloaded: {target}")
        return

    backups = list_backups()
    if not backups:
        print(f"No backups in {backups_dir()}")
    for day, path in backups:
        print(f"{day:%Y-%m-%d}  {os.path.getsize(path) / 1024:7.0f} KB  {path}")
    bucket = offsite_bucket()
    if bucket:
        remote = list_remote_backups(bucket)
        print(f"\nR2 bucket {bucket}: {len(remote)} copies")
        for day, key in remote:
            print(f"{day:%Y-%m-%d}  {key}")


if __name__ == "__main__":
    main()
