from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core import config
from core.scheduler.archive import archive_completed_month_logs, archive_today_images
from core.scheduler.recap import generate_daily_recap
from core.scheduler.reposts import send_daily_scheduled_reposts

_scheduler = None


def start_scheduler(bot):
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(send_daily_scheduled_reposts, 'cron', hour=config.REPOSTS_TIME[0], minute=config.REPOSTS_TIME[1], args=[bot])
    _scheduler.add_job(generate_daily_recap, 'cron', hour=config.RECAP_TIME[0], minute=config.RECAP_TIME[1], args=[bot])
    _scheduler.add_job(archive_today_images, 'cron', hour=config.ARCHIVE_IMAGES_TIME[0], minute=config.ARCHIVE_IMAGES_TIME[1], args=[bot])
    _scheduler.add_job(archive_completed_month_logs, 'cron', hour=config.ARCHIVE_LOGS_TIME[0], minute=config.ARCHIVE_LOGS_TIME[1])
    _scheduler.start()


def add_interval_job(func, minutes, args=None):
    """Registers a repeating job on the running scheduler (start_scheduler must have run); never overlaps itself."""
    if _scheduler is None:
        raise RuntimeError("Scheduler not started")
    _scheduler.add_job(func, 'interval', minutes=minutes, args=args or [], max_instances=1, coalesce=True)


def add_cron_job(func, hour, minute, args=None):
    """Registers a daily job at hour:minute (local time) on the running scheduler (start_scheduler must have run)."""
    if _scheduler is None:
        raise RuntimeError("Scheduler not started")
    _scheduler.add_job(func, 'cron', hour=hour, minute=minute, args=args or [])


def stop_scheduler():
    if _scheduler:
        _scheduler.shutdown()
