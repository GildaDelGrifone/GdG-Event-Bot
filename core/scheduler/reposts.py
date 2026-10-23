import logging
from datetime import datetime

from core import config
from core.db import get_scheduled_events_due
from utils.date_utils import DAYS_IT
from utils.templates.reposts import REPOST_UPDATE_REMINDER, format_reposts_digest_entry, format_reposts_digest_header

logger = logging.getLogger(__name__)


def format_reposts_digest(due, weekday_it, today_str):
    lines = [format_reposts_digest_header(weekday_it, today_str)]
    lines.extend(format_reposts_digest_entry(ev, event_date) for ev, event_date in due)
    lines.append(REPOST_UPDATE_REMINDER)
    return "\n".join(lines)


async def send_daily_scheduled_reposts(bot):
    """Daily job: tells ADMIN_CHAT_ID which scheduled templates need a reminder today (event date = today + advance_days)."""
    if not bot or not config.ADMIN_CHAT_ID:
        return

    now = datetime.now()
    weekday_it = DAYS_IT[now.weekday()]
    today_str = now.strftime("%d-%m-%Y")

    logger.info(f"Scheduler: Checking scheduled reposts for today ({weekday_it} {today_str})...")
    events = get_scheduled_events_due(now.date())
    if not events:
        logger.info(f"Scheduler: No events scheduled for reposting on {today_str}.")
        return

    try:
        await bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=format_reposts_digest(events, weekday_it, today_str), parse_mode="HTML")
        logger.info(f"Scheduler: Sent today's scheduled reposts notification ({len(events)} events) to admin chat.")
    except Exception as e:
        logger.error(f"Scheduler: Failed to send scheduled reposts notification to admin chat: {e}")
