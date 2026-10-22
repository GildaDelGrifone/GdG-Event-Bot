"""Nightly cleanup: removes cancelled events from the Eventbrite organizer account (Telegram is left untouched)."""
import asyncio
import logging
from datetime import datetime
from types import SimpleNamespace

from core import config
from core.db import clear_eventbrite_info, get_eventbrite_cleanup_candidates
from core.eventbrite import EventbriteError, delete_eventbrite_event, eventbrite_enabled
from bot.service.eventbrite import refresh_admin_card
from utils.templates.eventbrite import (
    format_cleanup_deleted, format_cleanup_failed, format_cleanup_kept, format_cleanup_label,
    format_cleanup_pending_orders, format_cleanup_refused,
)

logger = logging.getLogger(__name__)

RATE_LIMIT_ERROR = "HIT_RATE_LIMIT"


def _label(event):
    return format_cleanup_label(event['id'], event.get('title'))


def _already_gone(error):
    return error.status_code == 404 or error.error == "NOT_FOUND"


async def _send_summary(bot, deleted, kept):
    if not config.EVENTBRITE_CLEANUP_NOTIFICATIONS:
        deleted = []  # only problems that need an admin are reported
    if not (bot and config.ADMIN_CHAT_ID and (deleted or kept)):
        return
    parts = []
    if deleted:
        parts.append(format_cleanup_deleted(len(deleted), deleted))
    if kept:
        parts.append(format_cleanup_kept(kept))
    try:
        await bot.send_message(chat_id=config.ADMIN_CHAT_ID, text="\n".join(parts))
    except Exception as e:
        logger.error(f"Could not send the Eventbrite cleanup summary: {e}")


async def delete_cancelled_eventbrite_events(bot, today=None):
    """Deletes, on Eventbrite only, the cancelled events dated today or earlier, forgetting the link in the database.

    Events whose cancellation is still pending (orders left) or that Eventbrite refuses to delete are kept and reported."""
    if not eventbrite_enabled() or not config.EVENTBRITE_DELETE_CANCELLED:
        return
    now = today or datetime.now()
    ctx = SimpleNamespace(bot=bot)  # the services only use context.bot
    deleted, kept = [], []

    for event in get_eventbrite_cleanup_candidates((now.year, now.month, now.day)):
        label = _label(event)
        if event.get('eventbrite_status') == 'closed':
            kept.append(format_cleanup_pending_orders(label))
            continue
        try:
            try:
                await asyncio.to_thread(delete_eventbrite_event, event['eventbrite_event_id'])
            except EventbriteError as e:
                if not _already_gone(e):
                    raise
            clear_eventbrite_info(event['id'])
            deleted.append(label)
            logger.info(f"Eventbrite cleanup: deleted the Eventbrite event of #{event['id']}.")
            if bot:
                await refresh_admin_card(ctx, event['id'])
        except EventbriteError as e:
            if e.error == RATE_LIMIT_ERROR:
                logger.warning("Eventbrite rate limit hit; stopping the cleanup (it will retry tomorrow night).")
                break
            logger.warning(f"Eventbrite refused to delete the event of #{event['id']}: {e}")
            kept.append(format_cleanup_refused(label, e.error))
        except Exception as e:
            logger.error(f"Eventbrite cleanup failed for event #{event['id']}: {e}")
            kept.append(format_cleanup_failed(label, e))

    await _send_summary(bot, deleted, kept)
