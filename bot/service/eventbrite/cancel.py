"""Cancelling (unpublish, or close + per-order cancel links) and reactivating Eventbrite events."""
import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from core.db import set_eventbrite_info
from core.eventbrite import (
    EventbriteError, cancel_event, dashboard_url, event_payload, eventbrite_enabled, fetch_active_orders,
    order_cancel_url, publish_event, unpublish_event, update_event,
)
from core.eventbrite.tickets import update_ticket_quantity
from utils.templates.eventbrite import (
    EVENTBRITE_CANCELLED_CANNOT_REACTIVATE, EVENTBRITE_ORDERS_STILL_ACTIVE_PREFIX, EVENTBRITE_STILL_TELEGRAM_ACTIVE,
    format_eb_all_orders_cancelled, format_eb_already_cancelled, format_eb_cancel_failed, format_eb_cancel_incomplete,
    format_eb_cancelled_keep_telegram, format_eb_cancelled_too, format_eb_cannot_cancel_yet,
    format_eb_orders_to_cancel, format_eb_reactivate_failed, format_eb_reactivated, format_eb_taken_offline,
)
from utils.templates.keyboards import BUTTON_EB_CANCEL_DONE, BUTTON_EB_DASHBOARD, format_eb_order_button
from bot.service.eventbrite.common import _recreate_keyboard, notify_admin, refresh_admin_card
from bot.service.eventbrite.sync import _push_capacity, _push_content

logger = logging.getLogger(__name__)

MAX_ORDER_BUTTONS = 40  # keeps the admin message well under Telegram's inline keyboard limits


def _cancel_blocking(event, unpublish_if_empty=True):
    """Returns (outcome, orders): outcome is 'unpublished', 'canceled' or 'closed'; orders is fetch_active_orders().
    unpublish_if_empty=False cancels for good even without orders (Eventbrite-only cancellation)."""
    event_id, eb_id = event['id'], event['eventbrite_event_id']
    orders = fetch_active_orders(eb_id)
    eb_seats = sum(seats for _, seats in orders.values())

    if not orders and unpublish_if_empty:
        try:
            unpublish_event(eb_id)
            set_eventbrite_info(event_id, eventbrite_status='unpublished')
            return 'unpublished', orders
        except EventbriteError as e:
            logger.warning(f"Eventbrite refused to unpublish event #{event_id} ({e.error}); trying to cancel it.")

    # Close sales at the number sold and flag the title, then try the cancel API (refused while orders exist)
    cancelled = {**event, 'status': 'cancelled'}
    # Eventbrite rejects a quantity of 0 (NO_QUANTITY_TOTAL), and with no orders there is nothing to close anyway
    if event.get('eventbrite_ticket_class_id') and eb_seats:
        update_ticket_quantity(eb_id, event['eventbrite_ticket_class_id'], eb_seats)
        set_eventbrite_info(event_id, eventbrite_quantity_total=eb_seats)
    update_event(eb_id, event_payload(cancelled, include_dates=False))
    if _try_cancel(event_id, eb_id):
        return 'canceled', orders
    set_eventbrite_info(event_id, eventbrite_status='closed')
    return 'closed', orders


def _try_cancel(event_id, eb_id):
    try:
        cancel_event(eb_id)
    except EventbriteError as e:
        if e.error != 'ALREADY_CANCELED':
            logger.warning(f"Eventbrite refused to cancel event #{event_id} ({e.error}).")
            return False
        logger.info(f"Event #{event_id} was already cancelled on Eventbrite.")  # e.g. cancelled by hand
    set_eventbrite_info(event_id, eventbrite_status='canceled')
    return True


def _orders_cancel_message(event_id, eb_event_id, orders):
    """Text + keyboard with one "Cancel order" link per order: the API cannot cancel orders, the dashboard can."""
    shown = list(orders.items())[:MAX_ORDER_BUTTONS]
    rows = [
        [InlineKeyboardButton(format_eb_order_button(name, seats), url=order_cancel_url(eb_event_id, order_id))]
        for order_id, (name, seats) in shown
    ]
    rows.append([InlineKeyboardButton(BUTTON_EB_DASHBOARD, url=dashboard_url(eb_event_id))])
    rows.append([InlineKeyboardButton(BUTTON_EB_CANCEL_DONE, callback_data=f"eb_cancel_retry_{event_id}")])
    text = format_eb_orders_to_cancel(event_id, len(orders), hidden=len(orders) - MAX_ORDER_BUTTONS)
    return text, InlineKeyboardMarkup(rows)


async def cancel_on_eventbrite(context, event):
    """Mirrors a (confirmed) Telegram cancellation: unpublish when nobody booked; otherwise close sales, rename and send
    the admins one cancel link per order, since the API cannot cancel orders."""
    if not eventbrite_enabled() or not event or not event.get('eventbrite_event_id'):
        return
    if event.get('eventbrite_status') in ('canceled', 'draft', 'unpublished', 'closed'):
        return

    event_id = event['id']
    try:
        outcome, orders = await asyncio.to_thread(_cancel_blocking, event)
    except Exception as e:
        logger.error(f"Eventbrite cancellation failed for event #{event_id}: {e}")
        await notify_admin(context, config.ADMIN_CHAT_ID, format_eb_cancel_failed(event_id, e), event_id=event_id)
        return

    if outcome == 'unpublished':
        await notify_admin(context, config.ADMIN_CHAT_ID, format_eb_taken_offline(event_id), event_id=event_id)
    elif outcome == 'canceled':
        await notify_admin(context, config.ADMIN_CHAT_ID, format_eb_cancelled_too(event_id), event_id=event_id)
    else:
        text, keyboard = _orders_cancel_message(event_id, event['eventbrite_event_id'], orders)
        await notify_admin(context, config.ADMIN_CHAT_ID, text, reply_markup=keyboard, event_id=event_id)


async def finish_eventbrite_cancellation(context, event, admin_chat_id, from_poller=False, temporary_message=None):
    """Completes a 'closed' cancellation once every order has been cancelled from the dashboard.

    From the [🔁 …] button it re-sends the links of the orders still active; from the poller it stays quiet.
    `temporary_message` is the order-links message the button was pressed on: it is deleted once the event is cancelled.
    """
    if not eventbrite_enabled() or not event or event.get('eventbrite_status') != 'closed':
        if not from_poller and event and event.get('eventbrite_status') == 'canceled':
            await notify_admin(context, admin_chat_id, format_eb_already_cancelled(event['id']), event_id=event['id'])
        return
    event_id, eb_id = event['id'], event['eventbrite_event_id']
    try:
        orders = await asyncio.to_thread(fetch_active_orders, eb_id)
        if orders:
            if not from_poller:
                text, keyboard = _orders_cancel_message(event_id, eb_id, orders)
                await notify_admin(context, admin_chat_id, EVENTBRITE_ORDERS_STILL_ACTIVE_PREFIX + text, reply_markup=keyboard, event_id=event_id)
            return
        cancelled = await asyncio.to_thread(_try_cancel, event_id, eb_id)
    except Exception as e:
        logger.error(f"Could not complete the Eventbrite cancellation of event #{event_id}: {e}")
        if not from_poller:
            await notify_admin(context, admin_chat_id, format_eb_cancel_incomplete(event_id, e), event_id=event_id)
        return

    if cancelled:
        if temporary_message:
            try:
                await temporary_message.delete()
            except Exception as e:
                logger.warning(f"Could not delete the order-links message of event #{event_id}: {e}")
        await notify_admin(context, admin_chat_id,
                           format_eb_all_orders_cancelled(event_id), event_id=event_id)
        await refresh_admin_card(context, event_id)
    elif not from_poller:
        url = dashboard_url(eb_id)
        await notify_admin(context, admin_chat_id,
                           format_eb_cannot_cancel_yet(event_id, url),
                           reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(BUTTON_EB_DASHBOARD, url=url)]]), event_id=event_id)


async def cancel_only_on_eventbrite(context, event, admin_chat_id):
    """Cancels the Eventbrite event only: the Telegram event stays approved and nothing is posted to the discussion
    group (its booking reply just loses the Eventbrite link). Orders follow the same per-order link flow."""
    event_id = event['id']
    try:
        outcome, orders = await asyncio.to_thread(_cancel_blocking, event, False)
    except Exception as e:
        logger.error(f"Eventbrite-only cancellation failed for event #{event_id}: {e}")
        await notify_admin(context, admin_chat_id, format_eb_cancel_failed(event_id, e), event_id=event_id)
        return

    if outcome == 'canceled':
        await notify_admin(context, admin_chat_id, format_eb_cancelled_keep_telegram(event_id), event_id=event_id)
    else:
        text, keyboard = _orders_cancel_message(event_id, event['eventbrite_event_id'], orders)
        await notify_admin(context, admin_chat_id, text + EVENTBRITE_STILL_TELEGRAM_ACTIVE, reply_markup=keyboard, event_id=event_id)
    await refresh_admin_card(context, event_id)
    # Imported here because bot.service.posts imports this module for sync_eventbrite
    from bot.service.posts import update_event_messages
    await update_event_messages(context, event_id)  # removes the Eventbrite link from the discussion reply


def _reactivate_blocking(event):
    """Returns the warning to show, if any. The event is already 'approved' in the database."""
    eb_id, status = event['eventbrite_event_id'], event.get('eventbrite_status')
    warning = None
    if status == 'unpublished':
        publish_event(eb_id)
        set_eventbrite_info(event['id'], eventbrite_status='live')
        warning = _push_content(event)
    elif status == 'closed':
        update_event(eb_id, event_payload(event, include_dates=False))
        set_eventbrite_info(event['id'], eventbrite_status='live')
    _push_capacity(event, force=True)
    return warning


async def reactivate_on_eventbrite(context, event):
    """Mirrors a Telegram reactivation (see the cancel matrix); a cancelled Eventbrite event can only be re-created."""
    if not eventbrite_enabled() or not event or not event.get('eventbrite_event_id'):
        return
    event_id, status = event['id'], event.get('eventbrite_status')

    if status == 'canceled':
        await notify_admin(context, config.ADMIN_CHAT_ID,
                           EVENTBRITE_CANCELLED_CANNOT_REACTIVATE,
                           reply_markup=_recreate_keyboard(event_id), event_id=event_id)
        return
    if status not in ('unpublished', 'closed'):
        return

    try:
        warning = await asyncio.to_thread(_reactivate_blocking, event)
    except Exception as e:
        logger.error(f"Eventbrite reactivation failed for event #{event_id}: {e}")
        await notify_admin(context, config.ADMIN_CHAT_ID, format_eb_reactivate_failed(event_id, e), event_id=event_id)
        return
    if warning:
        await notify_admin(context, config.ADMIN_CHAT_ID, warning, event_id=event_id)
    await notify_admin(context, config.ADMIN_CHAT_ID, format_eb_reactivated(event_id), event_id=event_id)
