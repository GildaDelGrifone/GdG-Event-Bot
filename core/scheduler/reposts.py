import html
import logging
from datetime import datetime

from core import config
from core.db import get_scheduled_events_for_date
from utils.date_utils import DAYS_IT
from utils.templates import REPOST_UPDATE_REMINDER

logger = logging.getLogger(__name__)


def format_reposts_digest(events, weekday_it, today_str):
    lines = [f"📅 <b>Eventi programmati per il reposting di oggi ({weekday_it} {today_str}):</b>\n"]
    for ev in events:
        sched_id = ev['id']
        lines.append(
            f"• <b>{html.escape(ev.get('title') or 'Evento')}</b> (ID #{sched_id})\n"
            f"  👉 Invia per preparare il post: <code>/event_repost_invoke {sched_id}</code>\n"
        )
    lines.append(REPOST_UPDATE_REMINDER)
    return "\n".join(lines)


async def send_daily_scheduled_reposts(bot):
    """Daily 10:00 job: tells ADMIN_CHAT_ID which scheduled templates are due today, with invoke commands."""
    if not bot or not config.ADMIN_CHAT_ID:
        return

    now = datetime.now()
    weekday_it = DAYS_IT[now.weekday()]
    today_str = now.strftime("%d-%m-%Y")

    logger.info(f"Scheduler: Checking scheduled reposts for today ({weekday_it} {today_str})...")
    events = get_scheduled_events_for_date(today_str, weekday_it)
    if not events:
        logger.info(f"Scheduler: No events scheduled for reposting on {today_str}.")
        return

    try:
        await bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=format_reposts_digest(events, weekday_it, today_str), parse_mode="HTML")
        logger.info(f"Scheduler: Sent today's scheduled reposts notification ({len(events)} events) to admin chat.")
    except Exception as e:
        logger.error(f"Scheduler: Failed to send scheduled reposts notification to admin chat: {e}")
