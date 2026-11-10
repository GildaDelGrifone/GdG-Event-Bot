"""Polls Eventbrite for booking changes and mirrors them into the shared seat pool.

Each poll fetches the event (one call) and compares its `quantity_sold` with the Eventbrite seats we have stored. The
orders (needed for the attendees' names) are fetched only when they differ, plus a full check every
EVENTBRITE_FULL_SYNC_MINUTES as a safety net (e.g. one person cancels while another books between two polls).

New and bigger orders are applied at once. A smaller or missing order is applied only when two consecutive orders fetches
agree: Eventbrite sometimes answers with a list that briefly lacks an order (eventually consistent, degraded responses),
and trusting that single snapshot released and re-booked the same seat over and over, announcing every flip. Every
and applied order change is logged.

Churn: EVENTBRITE_CHURN_RELEASES releases by the same name on the same live event within EVENTBRITE_CHURN_WINDOW_MINUTES
silence that name's announcements on that event (saved in eventbrite_mutes) and send the admins one alert with the
name's order-cancel links and a [🔔 Riattiva annunci] button. Seats keep syncing; only the announcements stop.

Budget: about one call per tracked event per poll. With 10 events every 2 minutes that is about 300 calls per hour (plus
the periodic full checks), under Eventbrite's limits of 2,000 calls/hour and 48,000/day per application.
"""
import asyncio
import logging
import time
from collections import deque
from datetime import datetime
from types import SimpleNamespace

from core import config
from core.db import (
    apply_eventbrite_order,
    eventbrite_seat_count,
    get_event,
    get_eventbrite_mutes,
    get_eventbrite_reservations,
    get_eventbrite_tracked_events,
    get_reservations_for_event,
    mute_eventbrite_name,
    set_eventbrite_info,
)
from core.eventbrite import EventbriteError, eventbrite_enabled, fetch_active_orders, get_event as get_eventbrite_event
from utils.templates.common import format_event_title_link, format_seats_count
from utils.templates.eventbrite import (
    format_eb_churn_alert, format_eb_overbooking, format_eb_poll_booked, format_eb_poll_event_cancelled, format_eb_poll_released,
)
from bot.keyboards import get_eventbrite_churn_keyboard
from bot.service.eventbrite import finish_eventbrite_cancellation, is_gone, notify_admin, unlink_deleted_eventbrite_event
from bot.service.notices import send_discussion_notice
from bot.service.posts import update_event_messages
from bot.state import runtime_state

logger = logging.getLogger(__name__)

RATE_LIMIT_ERROR = "HIT_RATE_LIMIT"

# Bot event id -> _now() of its last full orders fetch (in memory: a restart simply triggers one full fetch)
_last_full_fetch = {}
# Bot event id -> {order id: seats seen} for drops seen once and not applied yet (confirmed by the next orders fetch)
_pending_releases = {}
# (bot event id, attendee name) -> _now() of its recent Eventbrite releases (churn detection; in memory)
_release_times = {}
# Bot event ids whose quantity_sold still disagreed with the orders after a full fetch (logged once)
_mismatch_logged = set()


def _now():
    return time.monotonic()


def _sold_quantity(eb_event):
    """Total tickets sold across the ticket classes, or None when the response carries no ticket classes."""
    classes = eb_event.get('ticket_classes')
    if not classes:
        return None
    return sum(int(tc.get('quantity_sold') or 0) for tc in classes)


def _full_sync_due(event_id, now):
    minutes = config.EVENTBRITE_FULL_SYNC_MINUTES
    last = _last_full_fetch.get(event_id)
    return minutes <= 0 or last is None or now - last >= minutes * 60


def _seats_label(count):
    return format_seats_count(count)


def _apply(event_id, order_id, name, seats, changes):
    result = apply_eventbrite_order(event_id, order_id, name, seats)
    if result:
        logger.info(f"Eventbrite #{event_id}: order {order_id} ({name}) {result[0]} -> {result[1]} seats.")
        changes.append((name, *result))


def _diff_orders(event_id, orders):
    """Applies the changed orders to the database; returns [(name, old_seats, new_seats, overbooked)].

    Increases are applied at once; a decrease (or a missing order) only when the previous fetch showed the same drop."""
    existing = {row['eventbrite_order_id']: row for row in get_eventbrite_reservations(event_id)}
    pending = _pending_releases.pop(event_id, {})
    still_pending = {}
    changes = []
    seen = {order_id: (name, seats) for order_id, (name, seats) in orders.items()}
    for order_id, row in existing.items():
        seen.setdefault(order_id, (row['full_name'], 0))
    for order_id, (name, seats) in seen.items():
        previous = existing.get(order_id)
        stored = previous['seats_booked'] if previous is not None else 0
        if seats > stored:
            _apply(event_id, order_id, name, seats, changes)
        elif seats < stored:
            if pending.get(order_id) == seats:
                _apply(event_id, order_id, name, seats, changes)
            else:
                still_pending[order_id] = seats
                logger.warning(f"Eventbrite #{event_id}: order {order_id} ({name}) shows {seats} seats instead of "
                               f"{stored} in this fetch; waiting for the next fetch to confirm.")
        elif order_id in pending:
            logger.info(f"Eventbrite #{event_id}: order {order_id} ({name}) is back at {stored} seats; "
                        f"the drop was transient and has been ignored.")
    if still_pending:
        _pending_releases[event_id] = still_pending
    return changes


def forget_churn(event_id, name=None):
    """Drops the release history of one name on the event (all names when None), e.g. when an admin unmutes it."""
    for key in [k for k in _release_times if k[0] == event_id and (name is None or k[1] == name)]:
        del _release_times[key]


def _track_churn(event_id, changes, muted):
    """Records the releases in `changes`; returns the names that just reached the churn limit and are not muted yet."""
    limit = config.EVENTBRITE_CHURN_RELEASES
    if limit <= 0:
        return []
    now, window = _now(), config.EVENTBRITE_CHURN_WINDOW_MINUTES * 60
    reached = []
    for name, old, new, _overbooked in changes:
        if new >= old:
            continue
        times = _release_times.setdefault((event_id, name), deque())
        times.append(now)
        while times and now - times[0] > window:
            times.popleft()
        if len(times) >= limit and name not in muted and name not in reached:
            reached.append(name)
    return reached


async def _silence(ctx, event, name):
    """Saves the mute and sends the admins the churn alert (order-cancel links + unmute button)."""
    event_id = event['id']
    mute_id = mute_eventbrite_name(event_id, name)
    releases = len(_release_times.get((event_id, name), ()))
    logger.warning(f"Eventbrite #{event_id}: {name} released seats {releases} times within "
                   f"{config.EVENTBRITE_CHURN_WINDOW_MINUTES} minutes; announcements silenced (mute {mute_id}).")
    orders = [(r['eventbrite_order_id'], r['full_name'], r['seats_booked'])
              for r in get_eventbrite_reservations(event_id) if r.get('full_name') == name]
    keyboard = get_eventbrite_churn_keyboard(event.get('eventbrite_event_id'), orders, mute_id) if mute_id else None
    text = format_eb_churn_alert(name, releases, config.EVENTBRITE_CHURN_WINDOW_MINUTES, format_event_title_link(event))
    await notify_admin(ctx, config.ADMIN_CHAT_ID, text, reply_markup=keyboard, event_id=event_id, parse_mode="HTML")


async def _check_cancellation(ctx, event, eb_event):
    if eb_event.get('status') != 'canceled' or event.get('eventbrite_status') == 'canceled':
        return
    set_eventbrite_info(event['id'], eventbrite_status='canceled')
    telegram_cancelled = event['status'] == 'cancelled' or event.get('eventbrite_status') == 'closed'  # a cancellation we started
    await notify_admin(ctx, config.ADMIN_CHAT_ID, format_eb_poll_event_cancelled(event['id'], telegram_cancelled), event_id=event['id'])


async def _announce(ctx, event, changes):
    title = format_event_title_link(event)
    for name, old, new, _overbooked in changes:
        delta = new - old
        if delta > 0:
            text = format_eb_poll_booked(name, _seats_label(delta), title)
        elif delta < 0:
            text = format_eb_poll_released(name, _seats_label(-delta), title)
        else:
            continue
        if event.get('telegram_message_id'):
            await send_discussion_notice(ctx, event, text, label="Eventbrite booking notice")
        else:  # Eventbrite-only event: no discussion group traffic, the admins keep track in their chat
            await notify_admin(ctx, config.ADMIN_CHAT_ID, text, event_id=event['id'], parse_mode="HTML")


async def _poll_event(ctx, event):
    event_id, eb_id = event['id'], event['eventbrite_event_id']
    try:
        eb_event = await asyncio.to_thread(get_eventbrite_event, eb_id)
    except EventbriteError as e:
        if not is_gone(e):
            raise
        await unlink_deleted_eventbrite_event(ctx, event_id)  # deleted by hand: stop polling it
        _last_full_fetch.pop(event_id, None)
        _pending_releases.pop(event_id, None)
        forget_churn(event_id)
        _mismatch_logged.discard(event_id)
        return
    await _check_cancellation(ctx, event, eb_event)

    # Same number sold as the seats we hold: nobody booked or cancelled, so the orders call would be wasted
    sold = _sold_quantity(eb_event)
    stored = eventbrite_seat_count(event_id)
    now = _now()
    orders = None
    changes = []
    # A drop seen once is confirmed (or dismissed) by the next fetch, so it is never left waiting for a full check
    if sold is None or sold != stored or event_id in _pending_releases or _full_sync_due(event_id, now):
        orders = await asyncio.to_thread(fetch_active_orders, eb_id)
        _last_full_fetch[event_id] = now
        changes = _diff_orders(event_id, orders)
        # A drop waiting for confirmation explains a gap with quantity_sold until the next fetch
        if sold is not None and event_id not in _pending_releases and eventbrite_seat_count(event_id) != sold:
            if event_id not in _mismatch_logged:
                _mismatch_logged.add(event_id)
                logger.warning(f"Eventbrite event #{event_id}: quantity_sold {sold} still differs from the active orders "
                               f"({eventbrite_seat_count(event_id)} seats); fetching orders on every poll until they agree.")
        else:
            _mismatch_logged.discard(event_id)

    if changes:
        await update_event_messages(ctx, event_id)
        current = get_event(event_id) or event
        # Seats keep syncing for cancelled events (on Telegram or Eventbrite only), but the group is not told and
        # releases do not count as churn (e.g. the admins cancelling every order of a cancelled event)
        if current.get('status') == 'approved' and current.get('eventbrite_status') == 'live':
            muted = {mute['name'] for mute in get_eventbrite_mutes(event_id)}
            for name in _track_churn(event_id, changes, muted):
                muted.add(name)
                await _silence(ctx, current, name)
            if runtime_state.eventbrite_booking_notifications:
                await _announce(ctx, current, [change for change in changes if change[0] not in muted])
        if any(change[3] for change in changes):
            max_seats = current.get('max_seats')
            telegram = [r for r in get_reservations_for_event(event_id) if r.get('source') != 'eventbrite']
            latest = telegram[-1] if telegram else None
            last_user = None
            if latest:
                last_user = f"@{latest['username']}" if latest.get('username') else latest.get('full_name') or 'sconosciuto'
            await notify_admin(
                ctx,
                config.ADMIN_CHAT_ID,
                format_eb_overbooking(event_id, current.get('booked_seats'), max_seats, last_user),
                event_id=event_id,
            )
    # Every order was cancelled from the dashboard: the cancel API now works, so finish the job
    current = get_event(event_id) or event
    no_orders = (not orders and event_id not in _pending_releases) if orders is not None else (sold == 0 and stored == 0)
    if no_orders and current.get('eventbrite_status') == 'closed':
        await finish_eventbrite_cancellation(ctx, current, config.ADMIN_CHAT_ID, from_poller=True)
    set_eventbrite_info(event_id, eventbrite_synced_at=datetime.now().isoformat(timespec='seconds'))


async def poll_event_now(ctx, event_id):
    """Polls one event right away (e.g. after a booking collided with Eventbrite); never raises."""
    event = get_event(event_id)
    if not eventbrite_enabled() or not event or event_id not in {e['id'] for e in get_eventbrite_tracked_events()}:
        return
    try:
        await _poll_event(ctx, event)
    except Exception as e:
        logger.warning(f"Immediate Eventbrite poll failed for event #{event_id}: {e}")


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
