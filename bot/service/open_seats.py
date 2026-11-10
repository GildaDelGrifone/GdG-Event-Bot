"""Daily list of the upcoming events that still have free seats, posted in the discussion group.

On a day with events (the automatic recap card goes out) the list follows the published recap and its links (send_open_seats_after_recap, called
from the recap forward in bot.handlers.recap); on the other days the OPEN_SEATS_REMINDER_TIME job registered by
main.post_init posts it (scheduled_open_seats_reminder). It is posted at most once a day.
"""
import logging
from datetime import date, datetime
from itertools import groupby

from telegram.error import TelegramError

from core import config
from core.db import get_pending_events_for_recap, get_upcoming_events
from utils.date_utils import DAYS_IT, event_date_tuple
from utils.templates.common import format_event_title_link
from utils.templates.public import (
    OPEN_SEATS_TITLE, format_open_seats_count, format_open_seats_day_header, format_open_seats_entry,
)
from bot.common.messages import with_html_fallback
from bot.state import runtime_state

logger = logging.getLogger(__name__)

# Longest message sent; a longer list is split between day blocks (Telegram's limit is 4096)
MESSAGE_LIMIT = 3800


def has_free_seats(event):
    max_seats = event.get('max_seats')
    return max_seats is None or int(event.get('booked_seats') or 0) < int(max_seats)


def open_seat_events(now=None):
    """Approved events dated tomorrow or later, posted on the channel, with free seats (or no limit), by date."""
    return [
        ev for ev in get_upcoming_events(include_today=False, now=now)
        if ev.get('status') == 'approved' and ev.get('message_link') and event_date_tuple(ev) and has_free_seats(ev)
    ]


def _day_block(day, events):
    weekday = DAYS_IT[date(*day).weekday()]
    lines = [format_open_seats_day_header(f"{weekday} {day[2]:02d}-{day[1]:02d}")]
    lines += [format_open_seats_entry(format_event_title_link(ev), ev.get('system'), format_open_seats_count(ev)) for ev in events]
    return "\n".join(lines)


def build_open_seats_messages(events):
    """The reminder texts for `events` (sorted by date): one header, then one block per day; split between days when too long."""
    messages, current = [], OPEN_SEATS_TITLE
    for day, day_events in groupby(events, key=event_date_tuple):
        block = _day_block(day, list(day_events))
        if current and len(current) + len(block) + 2 > MESSAGE_LIMIT:
            messages.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    if events:
        messages.append(current)
    return messages


async def send_open_seats_reminder(bot, now=None):
    """Posts the open-seats list in the discussion group; nothing is sent when no event qualifies. Returns the events listed."""
    if not config.DISCUSSION_GROUP_ID:
        logger.info("Open seats reminder: DISCUSSION_GROUP_ID is not set, nothing sent.")
        return 0
    events = open_seat_events(now)
    if not events:
        logger.info("Open seats reminder: no upcoming event with free seats, nothing sent.")
        return 0
    for text in build_open_seats_messages(events):
        try:
            await with_html_fallback(lambda **kw: bot.send_message(
                chat_id=config.DISCUSSION_GROUP_ID, text=text, disable_web_page_preview=True, **kw,
            ))
        except TelegramError as e:
            logger.warning(f"Open seats reminder: could not post in the discussion group: {e}")
            return 0
    runtime_state.open_seats_sent_on = _day_key(now)
    logger.info(f"Open seats reminder: {len(events)} events with free seats posted in the discussion group.")
    return len(events)


def _day_key(now=None):
    return (now or datetime.now()).strftime("%d-%m-%Y")


def recap_follows_today(now=None):
    """True when today has events: the daily recap card goes out (same query as the recap job), and the list waits for
    the published recap."""
    return bool(get_pending_events_for_recap(_day_key(now)))


async def scheduled_open_seats_reminder(bot, now=None):
    """The OPEN_SEATS_REMINDER_TIME job: posts the list, unless it was already posted today or the recap will carry it."""
    if runtime_state.open_seats_sent_on == _day_key(now):
        logger.info("Open seats reminder: already posted today, skipped.")
        return 0
    if recap_follows_today(now):
        logger.info("Open seats reminder: recap day with events, the list will follow the published recap.")
        return 0
    return await send_open_seats_reminder(bot, now)


async def send_open_seats_after_recap(bot, now=None):
    """Posts the list right after a published recap and its links, unless it was already posted today."""
    if not config.OPEN_SEATS_REMINDER_ENABLED or runtime_state.open_seats_sent_on == _day_key(now):
        return 0
    return await send_open_seats_reminder(bot, now)
