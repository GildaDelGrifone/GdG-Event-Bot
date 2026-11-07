"""Nightly SQLite backup: a gzipped snapshot per day in DATA_DIR/backups, rotated to a few daily + weekly copies."""
import asyncio
import gzip
import logging
import os
import re
import shutil
import sqlite3
from datetime import date, datetime

from core import config
from utils.templates.control import format_db_backup_failed

logger = logging.getLogger(__name__)

BACKUP_PREFIX = "bot_database_"
BACKUP_SUFFIX = ".db.gz"
_BACKUP_NAME = re.compile(r"^bot_database_(\d{4}-\d{2}-\d{2})\.db\.gz$")


def backups_dir():
    return os.path.join(config.DATA_DIR, "backups")


def list_backups(directory=None):
    """Returns [(date, path)] of the backup files in directory, oldest first; other files are ignored."""
    directory = directory or backups_dir()
    if not os.path.isdir(directory):
        return []
    found = []
    for name in os.listdir(directory):
        match = _BACKUP_NAME.match(name)
        if not match:
            continue
        try:
            day = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        found.append((day, os.path.join(directory, name)))
    return sorted(found)


def backups_to_keep(days, keep_days, keep_weeks):
    """The dates to keep: the newest keep_days, plus the oldest backup of each of the newest keep_weeks ISO weeks."""
    days = sorted(set(days))
    keep = set(days[-keep_days:]) if keep_days > 0 else set()
    first_of_week = {}
    for day in days:
        first_of_week.setdefault(day.isocalendar()[:2], day)
    for week in sorted(first_of_week)[-keep_weeks:] if keep_weeks > 0 else []:
        keep.add(first_of_week[week])
    return keep


def prune_backups(directory, keep_days, keep_weeks):
    """Deletes the backup files not selected by backups_to_keep; returns the number of files kept."""
    backups = list_backups(directory)
    keep = backups_to_keep([day for day, _ in backups], keep_days, keep_weeks)
    for day, path in backups:
        if day in keep:
            continue
        try:
            os.remove(path)
            logger.info(f"DB backup: removed old copy {os.path.basename(path)}")
        except OSError as e:
            logger.warning(f"DB backup: could not remove {path}: {e}")
    return len(keep)


def _snapshot(destination):
    """Copies the live database (WAL included) with SQLite's online backup API and checks the copy."""
    source = sqlite3.connect(config.DB_PATH)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
        result = target.execute("PRAGMA integrity_check").fetchone()
    finally:
        target.close()
        source.close()
    if not result or result[0] != "ok":
        raise RuntimeError(f"integrity check failed on the copy: {result[0] if result else 'no result'}")


def backup_database(today=None):
    """Writes DATA_DIR/backups/bot_database_<date>.db.gz and prunes old copies.

    Returns the backup path, or None when backups are disabled (DB_BACKUP_DAYS <= 0). Raises on failure,
    leaving the existing backups untouched.
    """
    if config.DB_BACKUP_DAYS <= 0:
        logger.info("DB backup: disabled (DB_BACKUP_DAYS=0).")
        return None
    if not os.path.exists(config.DB_PATH):
        raise FileNotFoundError(f"database not found: {config.DB_PATH}")

    directory = backups_dir()
    os.makedirs(directory, exist_ok=True)
    day = today or date.today()
    final_path = os.path.join(directory, f"{BACKUP_PREFIX}{day:%Y-%m-%d}{BACKUP_SUFFIX}")
    raw_tmp = final_path + ".raw.tmp"
    gz_tmp = final_path + ".tmp"
    try:
        _snapshot(raw_tmp)
        with open(raw_tmp, "rb") as src, gzip.open(gz_tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
        os.replace(gz_tmp, final_path)
    finally:
        for leftover in (raw_tmp, gz_tmp):
            if os.path.exists(leftover):
                os.remove(leftover)

    kept = prune_backups(directory, config.DB_BACKUP_DAYS, config.DB_BACKUP_WEEKS)
    size_kb = os.path.getsize(final_path) / 1024
    logger.info(f"DB backup: saved {os.path.basename(final_path)} ({size_kb:.0f} KB), {kept} copies kept.")
    return final_path


async def run_database_backup(bot):
    """Scheduler job: backs up the database in a worker thread and alerts the admins if it fails."""
    try:
        await asyncio.to_thread(backup_database)
    except Exception as e:
        logger.error(f"DB backup failed: {e}")
        if config.ADMIN_CHAT_ID:
            try:
                await bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=format_db_backup_failed(e))
            except Exception as notify_error:
                logger.error(f"DB backup: could not notify the admins: {notify_error}")
