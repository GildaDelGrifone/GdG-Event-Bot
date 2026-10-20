"""Polls Eventbrite for booking changes and mirrors them into the shared seat pool.

Budget: two Eventbrite calls per tracked event per poll. With 10 events every 2 minutes that is about 600 calls per hour,
under Eventbrite's 2000-per-hour token limit.
"""
import asyncio
import html
import logging
from datetime import datetime
from types import SimpleNamespace

from core import config
from core.db import (
    apply_eventbrite_order,
    get_event,
    get_eventbrite_reservations,
    get_eventbrite_tracked_events,
    set_eventbrite_info,
)
from core.eventbrite import EventbriteError, eventbrite_enabled, fetch_active_orders, get_event as get_eventbrite_event
from utils.templates import format_event_title_link
from bot.service.eventbrite import finish_eventbrite_cancellation
from bot.service.notices import send_discussion_notice
from bot.service.posts import update_event_messages

logger = logging.getLogger(__name__)

RATE_LIMIT_ERROR = "HIT_RATE_LIMIT"


def _fetch(eb_id):
    return get_eventbrite_event(eb_id), fetch_active_orders(eb_id)


def _seats_label(count):
    return f"{count} posto" if count == 1 else f"{count} posti"


def _diff_orders(event_id, orders):
    """Applies every changed order to the database; returns [(name, old_seats, new_seats, overbooked)]."""
    existing = {row['eventbrite_order_id']: row for row in get_eventbrite_reservations(event_id)}
    changes = []
    for order_id, (name, seats) in orders.items():
        previous = existing.get(order_id)
        if previous is not None and previous['seats_booked'] == seats:
            continue
        result = apply_eventbrite_order(event_id, order_id, name, seats)
        if result:
            changes.append((name, *result))
    for order_id, row in existing.items():
        if order_id not in orders:
            result = apply_eventbrite_order(event_id, order_id, row['full_name'], 0)
            if result:
                changes.append((row['full_name'], *result))
    return changes


async def _notify_admins(ctx, text):
    if not config.ADMIN_CHAT_ID:
        return
    try:
        await ctx.bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=text)
    except Exception as e:
        logger.error(f"Could not send Eventbrite poll notice to admin chat: {e}")


async def _check_cancellation(ctx, event, eb_event):
    if eb_event.get('status') != 'canceled' or event.get('eventbrite_status') == 'canceled':
        return
    set_eventbrite_info(event['id'], eventbrite_status='canceled')
    if event['status'] == 'cancelled' or event.get('eventbrite_status') == 'closed':  # a cancellation we started
        await _notify_admins(ctx, f"✅ Evento #{event['id']} annullato su Eventbrite (iscritti avvisati da Eventbrite)")
    else:
        await _notify_admins(ctx, f"⚠️ Evento #{event['id']} annullato su Eventbrite ma attivo su Telegram")


async def _announce(ctx, event, changes):
    title = format_event_title_link(event)
    for name, old, new, _overbooked in changes:
        delta = new - old
        if delta > 0:
            text = f"🎟️ {html.escape(name)} ha prenotato {_seats_label(delta)} tramite Eventbrite per: {title}"
        elif delta < 0:
            text = f"❌ {html.escape(name)} ha liberato {_seats_label(-delta)} (Eventbrite) per: {title}"
        else:
            continue
        await send_discussion_notice(ctx, event, text, label="Eventbrite booking notice")


async def _poll_event(ctx, event):
    event_id = event['id']
    eb_event, orders = await asyncio.to_thread(_fetch, event['eventbrite_event_id'])
    await _check_cancellation(ctx, event, eb_event)

    changes = _diff_orders(event_id, orders)
    if changes:
        await update_event_messages(ctx, event_id)
        current = get_event(event_id) or event
        # Seats keep syncing for cancelled events (on Telegram or Eventbrite only), but the group is not told
        if (config.EVENTBRITE_BOOKING_NOTIFICATIONS and current.get('status') == 'approved'
                and current.get('eventbrite_status') == 'live'):
            await _announce(ctx, current, changes)
        if any(change[3] for change in changes):
            max_seats = current.get('max_seats')
            await _notify_admins(
                ctx,
                f"⚠️ Overbooking su #{event_id}: {current.get('booked_seats')}/{max_seats} "
                "(prenotazione Eventbrite arrivata in contemporanea)",
            )
    # Every order was cancelled from the dashboard: the cancel API now works, so finish the job
    current = get_event(event_id) or event
    if not orders and current.get('eventbrite_status') == 'closed':
        await finish_eventbrite_cancellation(ctx, current, config.ADMIN_CHAT_ID, from_poller=True)
    set_eventbrite_info(event_id, eventbrite_synced_at=datetime.now().isoformat(timespec='seconds'))


async def poll_eventbrite_bookings(bot):
    """Scheduler job: one pass over every tracked event; an error on one event never blocks the others."""
    if not eventbrite_enabled():
        return
    ctx = SimpleNamespace(bot=bot)  # the services only use context.bot
    for event in get_eventbrite_tracked_events():
        try:
            await _poll_event(ctx, event)
        except EventbriteError as e:
            if e.error == RATE_LIMIT_ERROR:
                logger.warning("Eventbrite rate limit hit; stopping this poll cycle.")
                return
            logger.error(f"Eventbrite poll failed for event #{event['id']}: {e}")
        except Exception as e:
            logger.error(f"Eventbrite poll failed for event #{event['id']}: {e}")
