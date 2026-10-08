import os
import re
import sys
import zipfile
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

_LOG_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

# These helpers run inside the logging handler itself, so problems are reported on stderr instead of via logging.


def _logs_from_ended_months(logs_dir, now):
    """{(year, month): [paths]} for dated, non-zip log files from months before now's month."""
    by_month = {}
    for fname in os.listdir(logs_dir):
        fpath = os.path.join(logs_dir, fname)
        if not os.path.isfile(fpath) or fname.endswith(".zip"):
            continue
        m = _LOG_DATE_RE.search(fname)
        if not m:
            continue
        month = (int(m.group(1)), int(m.group(2)))
        if month < (now.year, now.month):
            by_month.setdefault(month, []).append(fpath)
    return by_month


def _zip_and_remove(zip_path, files):
    with zipfile.ZipFile(zip_path, 'a', zipfile.ZIP_DEFLATED) as zipf:
        existing = set(zipf.namelist())
        for file_path in files:
            arcname = os.path.basename(file_path)
            if arcname not in existing:
                zipf.write(file_path, arcname)

    for file_path in files:
        try:
            os.remove(file_path)
        except OSError as e:
            sys.stderr.write(f"Warning: Could not remove log file {file_path}: {e}\n")


def zip_completed_months(logs_dir: str, current_date: datetime | None = None) -> list[str]:
    """Moves daily logs of ended months into bot_logs_YYYY-MM.zip; returns the zip paths created or updated."""
    if not os.path.exists(logs_dir):
        return []

    archived_zips = []
    for (year, month), files in sorted(_logs_from_ended_months(logs_dir, current_date or datetime.now()).items()):
        zip_path = os.path.join(logs_dir, f"bot_logs_{year:04d}-{month:02d}.zip")
        try:
            _zip_and_remove(zip_path, files)
            archived_zips.append(zip_path)
        except Exception as e:
            sys.stderr.write(f"Error creating zip archive {zip_path}: {e}\n")
    return archived_zips


class DailyMonthlyLogHandler(TimedRotatingFileHandler):
    """Rotates daily at midnight and, on setup and every rollover, zips the daily logs of ended months."""

    def __init__(self, filename, when="midnight", interval=1, backupCount=0, encoding="utf-8", **kwargs):
        super().__init__(filename, when=when, interval=interval, backupCount=backupCount, encoding=encoding, **kwargs)
        self.check_and_zip()

    def check_and_zip(self):
        try:
            zip_completed_months(os.path.dirname(self.baseFilename))
        except Exception as e:
            sys.stderr.write(f"Error checking and zipping monthly logs: {e}\n")

    def doRollover(self):
        super().doRollover()
        self.check_and_zip()
