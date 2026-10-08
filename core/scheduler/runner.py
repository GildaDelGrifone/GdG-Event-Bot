from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.scheduler.archive import archive_completed_month_logs, archive_today_images
from core.scheduler.recap import generate_daily_recap
from core.scheduler.reposts import send_daily_scheduled_reposts

_scheduler = None


def start_scheduler(bot):
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(send_daily_scheduled_reposts, 'cron', hour=10, minute=0, args=[bot])
    _scheduler.add_job(generate_daily_recap, 'cron', hour=16, minute=0, args=[bot])
    _scheduler.add_job(archive_today_images, 'cron', hour=23, minute=59, args=[bot])
    _scheduler.add_job(archive_completed_month_logs, 'cron', hour=0, minute=5)
    _scheduler.start()


def stop_scheduler():
    if _scheduler:
        _scheduler.shutdown()
