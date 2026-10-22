"""Telegram-side Eventbrite flows: publish, sync (capacity/content/logo), cancel and reactivate.

Every Eventbrite call is blocking, so the work runs in asyncio.to_thread. Sync errors are reported to the admins and
never raised into the Telegram flow that triggered them.
"""
import asyncio
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from core.db import clear_eventbrite_info, eventbrite_seat_count, get_event, set_eventbrite_info
from core.eventbrite import (
    EventbriteError,
    add_event_to_collection,
    cancel_event,
    create_event,
    create_free_ticket_class,
    dashboard_url,
    description_modules,
    event_payload,
    event_start_end,
    eventbrite_enabled,
    eventbrite_venue_ids,
    fetch_active_orders,
    get_venue,
    order_cancel_url,
    publish_event,
    remove_event_from_collection,
    set_description,
    ticket_quantity,
    unpublish_event,
    update_event,
    upload_logo,
)
from core.eventbrite.media import short_reason
from core.eventbrite.tickets import update_ticket_capacity, update_ticket_quantity
from bot.common.messages import is_not_modified_error
from bot.keyboards import get_approved_event_keyboard, get_cancelled_event_keyboard
from bot.state import runtime_state
from utils.templates.common import format_event_id_not_found
from utils.templates.eventbrite import (
    DATE_NOT_UPDATED, EVENTBRITE_CANCELLED_CANNOT_REACTIVATE, EVENTBRITE_MUST_BE_APPROVED,
    EVENTBRITE_ORDERS_STILL_ACTIVE_PREFIX, EVENTBRITE_STILL_TELEGRAM_ACTIVE, NOT_CONFIGURED,
    format_eb_all_orders_cancelled, format_eb_already_cancelled, format_eb_already_published, format_eb_cancel_failed,
    format_eb_cancel_incomplete, format_eb_cancelled_keep_telegram, format_eb_cancelled_too,
    format_eb_cannot_cancel_yet, format_eb_collection_warning, format_eb_error, format_eb_link_removed,
    format_eb_logo_not_updated, format_eb_logo_not_uploaded, format_eb_logo_uploaded, format_eb_no_image,
    format_eb_not_active, format_eb_orders_to_cancel, format_eb_publish_failed, format_eb_publish_in_progress,
    format_eb_published, format_eb_reactivate_failed, format_eb_reactivated, format_eb_sync_failed,
    format_eb_taken_offline,
)
from utils.templates.keyboards import (
    BUTTON_EB_CANCEL_DONE, BUTTON_EB_DASHBOARD, BUTTON_EB_RECREATE, BUTTON_EB_RETRY_LOGO, format_eb_order_button,
)

logger = logging.getLogger(__name__)

MAX_ORDER_BUTTONS = 40  # keeps the admin message well under Telegram's inline keyboard limits


def _eb_seats_and_quantity(event):
    eb_seats = eventbrite_seat_count(event['id'])
    return eb_seats, ticket_quantity(event, eb_seats, config.EVENTBRITE_UNLIMITED_CAPACITY)


async def notify_admin(context, chat_id, text, reply_markup=None, event_id=None, parse_mode=None):
    """Plain-text notice (HTML with parse_mode). With event_id, in the admin chat, it replies to the event's admin card (plain send if the
    card is gone), like the other admin notices."""
    if not chat_id:
        return
    kwargs = dict(chat_id=chat_id, text=text, reply_markup=reply_markup, disable_web_page_preview=True, parse_mode=parse_mode)
    card_id = None
    if event_id and str(chat_id) == str(config.ADMIN_CHAT_ID):
        event = get_event(event_id)
        card_id = event.get('admin_message_id') if event else None
    try:
        if card_id:
            try:
                await context.bot.send_message(reply_to_message_id=card_id, **kwargs)
                return
            except Exception as e:
                logger.warning(f"Failed to send Eventbrite notice as reply to {card_id}: {e}")
        await context.bot.send_message(**kwargs)
    except Exception as e:
        logger.error(f"Could not send Eventbrite notice to admin chat: {e}")


async def refresh_admin_card(context, event_id):
    """Swaps the buttons of the event's admin card (approved or cancelled) to match the current Eventbrite state."""
    event = get_event(event_id)
    admin_message_id = event.get('admin_message_id') if event else None
    if not (admin_message_id and config.ADMIN_CHAT_ID):
        return
    if event.get('status') == 'approved':
        keyboard = get_approved_event_keyboard(event_id, event)
    elif event.get('status') == 'cancelled':
        keyboard = get_cancelled_event_keyboard(event_id)
    else:
        return
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=config.ADMIN_CHAT_ID, message_id=admin_message_id, reply_markup=keyboard,
        )
    except Exception as e:
        if not is_not_modified_error(e) and "message to edit not found" not in str(e).lower():
            logger.warning(f"Could not refresh admin card of event #{event_id}: {e}")


def _logo_retry_keyboard(event_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton(BUTTON_EB_RETRY_LOGO, callback_data=f"eb_logo_{event_id}")]])


def _failure_reason(error):
    """Short, single-line reason for an admin message (EventbriteError descriptions are already short)."""
    return short_reason(getattr(error, 'description', None) or str(error)) or type(error).__name__


def venue_name(venue_id):
    """Eventbrite's name for a venue (blocking; cached until restart, the id itself if the lookup fails)."""
    names = runtime_state.venue_names
    if venue_id not in names:
        try:
            names[venue_id] = get_venue(venue_id).get('name') or venue_id
        except Exception as e:
            logger.warning(f"Could not read Eventbrite venue {venue_id}: {e}")
            return venue_id
    return names[venue_id]


def _recreate_keyboard(event_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton(BUTTON_EB_RECREATE, callback_data=f"eb_recreate_{event_id}")]])


def _is_full(event):
    """Full = limited capacity with nothing left to sell. Unlimited (max_seats NULL) is never full; 0/0 Completo is."""
    if event.get('max_seats') is None:
        return False
    eb_seats, quantity = _eb_seats_and_quantity(event)
    return quantity - eb_seats <= 0


# ---------------------------------------------------------------- publish

def _collections_for(event):
    """(collection to join, the other one) for the event's type; either may be None when not configured."""
    roleplay, boardgames = config.EVENTBRITE_COLLECTION_ROLEPLAY, config.EVENTBRITE_COLLECTION_BOARDGAMES
    return (roleplay, boardgames) if event.get('is_roleplay') else (boardgames, roleplay)


def _assign_collection(event, leave_other=False):
    """Puts the Eventbrite event in the Collection of its type (roleplay / board games). Returns a warning or None:
    collections are cosmetic and not in the public API docs, so a failure never blocks anything."""
    target, other = _collections_for(event)
    if not target:
        return None
    eb_id = event['eventbrite_event_id']
    try:
        if leave_other and other:
            try:
                remove_event_from_collection(other, eb_id)
            except EventbriteError:
                pass  # was not in it
        add_event_to_collection(target, eb_id)
    except Exception as e:
        logger.warning(f"Could not add Eventbrite event of #{event['id']} to collection {target}: {e}")
        return format_eb_collection_warning(event['id'], _failure_reason(e))
    return None


def _publish_blocking(event, start_end):
    """Runs the publish steps in order, storing ids after each one so a failure can resume from the draft.
    Returns (eventbrite event JSON-ish dict with id/url, logo failure reason or None, collection warning or None)."""
    event_id = event['id']
    logo_error = None
    eb_id, url = event.get('eventbrite_event_id'), event.get('eventbrite_url')

    if not eb_id:
        if not event.get('eventbrite_venue_id'):  # fixed now, so syncs and a resumed draft keep this venue
            venue_id = runtime_state.eventbrite_venue if runtime_state.eventbrite_venue in eventbrite_venue_ids() else config.EVENTBRITE_VENUE_ID
            set_eventbrite_info(event_id, eventbrite_venue_id=venue_id)
            event = {**event, 'eventbrite_venue_id': venue_id}
        created = create_event(event_payload(event))
        eb_id, url = created['id'], created.get('url')
        set_eventbrite_info(event_id, eventbrite_event_id=eb_id, eventbrite_url=url,
                            eventbrite_status='draft', eventbrite_content_version=0)

    quantity = event.get('eventbrite_quantity_total')
    if not event.get('eventbrite_ticket_class_id'):
        # No seat left: the event is published as sold out (a 1-seat hidden ticket, 0 = "sales closed" in the database)
        closed = _is_full(event)
        _, quantity = _eb_seats_and_quantity(event)
        if closed:
            quantity = 0
        ticket_class = create_free_ticket_class(eb_id, quantity or 1, start_end[1], closed=closed)
        set_eventbrite_info(event_id, eventbrite_ticket_class_id=ticket_class['id'], eventbrite_quantity_total=quantity)

    image_path = event.get('image_path')
    if image_path and os.path.exists(image_path):
        try:
            update_event(eb_id, {"logo_id": upload_logo(image_path)})
        except Exception as e:
            logger.warning(f"Eventbrite logo upload failed for event #{event_id}: {e}")
            logo_error = _failure_reason(e)

    version = int(event.get('eventbrite_content_version') or 0) + 1
    set_eventbrite_info(event_id, eventbrite_content_version=set_description(eb_id, description_modules(event), version))

    publish_event(eb_id)
    set_eventbrite_info(event_id, eventbrite_status='live', eventbrite_url=url, eventbrite_quantity_total=quantity)
    collection_warning = _assign_collection({**event, 'eventbrite_event_id': eb_id})
    return {"id": eb_id, "url": url, "sold_out": quantity == 0}, logo_error, collection_warning


def is_gone(error):
    """True when Eventbrite says the event does not exist any more (e.g. it was deleted by hand in the dashboard)."""
    return isinstance(error, EventbriteError) and error.error == 'NOT_FOUND'


async def unlink_deleted_eventbrite_event(context, event_id):
    """Forgets an Eventbrite event that no longer exists, tells the admins and refreshes the card. Idempotent."""
    event = get_event(event_id)
    if not event or not event.get('eventbrite_event_id'):
        return
    clear_eventbrite_info(event_id)
    logger.info(f"The Eventbrite event of #{event_id} no longer exists; link removed.")
    text = format_eb_link_removed(event_id, can_republish=event.get('status') == 'approved')
    await notify_admin(context, config.ADMIN_CHAT_ID, text, event_id=event_id)
    await refresh_admin_card(context, event_id)


async def publish_event_to_eventbrite(context, event_id, admin_chat_id):
    """Publishes an approved event on Eventbrite (shared by the button and /event_publish_eventbrite). Idempotent."""
    if not eventbrite_enabled():
        await notify_admin(context, admin_chat_id, NOT_CONFIGURED)
        return

    event = get_event(event_id)
    if not event:
        await notify_admin(context, admin_chat_id, format_event_id_not_found(event_id))
        return
    if event.get('status') != 'approved':
        await notify_admin(context, admin_chat_id, EVENTBRITE_MUST_BE_APPROVED, event_id=event_id)
        return

    eb_status = event.get('eventbrite_status')
    if event.get('eventbrite_event_id') and eb_status != 'draft':
        if eb_status == 'canceled':
            await notify_admin(context, admin_chat_id,
                               EVENTBRITE_CANCELLED_CANNOT_REACTIVATE,
                               reply_markup=_recreate_keyboard(event_id), event_id=event_id)
        else:
            await notify_admin(context, admin_chat_id, format_eb_already_published(event.get('eventbrite_url')), event_id=event_id)
        return

    try:
        start_end = event_start_end(event)
    except ValueError as e:
        await notify_admin(context, admin_chat_id, format_eb_error(e), event_id=event_id)
        return

    try:
        try:
            result, logo_error, collection_warning = await asyncio.to_thread(_publish_blocking, event, start_end)
        except EventbriteError as e:
            if not (is_gone(e) and event.get('eventbrite_event_id')):
                raise
            # The draft we were resuming was deleted by hand: start again from scratch, once
            logger.info(f"The draft Eventbrite event of #{event_id} no longer exists; creating a new one.")
            clear_eventbrite_info(event_id)
            event = get_event(event_id)
            result, logo_error, collection_warning = await asyncio.to_thread(_publish_blocking, event, start_end)
    except Exception as e:
        logger.error(f"Eventbrite publish failed for event #{event_id}: {e}")
        await notify_admin(context, admin_chat_id,
                           format_eb_publish_failed(event_id, e), event_id=event_id)
        return

    if logo_error:
        await notify_admin(context, admin_chat_id, format_eb_logo_not_uploaded(logo_error),
                           reply_markup=_logo_retry_keyboard(event_id), event_id=event_id)
    if collection_warning:
        await notify_admin(context, admin_chat_id, collection_warning, event_id=event_id)
    venue = None
    if len(eventbrite_venue_ids()) > 1:
        venue_id = (get_event(event_id) or {}).get('eventbrite_venue_id')
        if venue_id:
            venue = await asyncio.to_thread(venue_name, venue_id)
    text = format_eb_published(result['url'], sold_out=result.get('sold_out'), venue=venue)
    await notify_admin(context, admin_chat_id, text, event_id=event_id)
    await refresh_admin_card(context, event_id)
    # Imported here because bot.service.posts imports this module for sync_eventbrite
    from bot.service.posts import update_event_messages
    await update_event_messages(context, event_id)


# ---------------------------------------------------------------- sync

def _update_capacity(event, eb_seats, quantity):
    """Pushes the ticket total (closing sales when no seat is left, see update_ticket_capacity); returns the response."""
    try:
        sales_end = event_start_end(event)[1]
    except ValueError:  # past or undated event: leave the sales end alone
        sales_end = None
    return update_ticket_capacity(event['eventbrite_event_id'], event['eventbrite_ticket_class_id'], quantity, eb_seats, sales_end)


def _push_capacity(event, force=False):
    eb_id, tc_id = event['eventbrite_event_id'], event.get('eventbrite_ticket_class_id')
    if not tc_id:
        logger.warning(f"Event #{event['id']} has no Eventbrite ticket class; capacity not pushed.")
        return
    eb_seats, quantity = _eb_seats_and_quantity(event)
    if force or quantity != event.get('eventbrite_quantity_total'):
        _update_capacity(event, eb_seats, quantity)
        set_eventbrite_info(event['id'], eventbrite_quantity_total=quantity)


def _reserve_blocking(event):
    """Pushes the new ticket total and reads quantity_sold from the same response: True when the seat is still ours."""
    eb_seats, quantity = _eb_seats_and_quantity(event)
    try:
        response = _update_capacity(event, eb_seats, quantity)
    except EventbriteError as e:
        # Eventbrite refuses a total below what it already sold: the last seat went there first
        if e.status_code == 400 and 'quantity' in f"{e.error} {e.description}".lower():
            return False
        raise
    set_eventbrite_info(event['id'], eventbrite_quantity_total=quantity)
    sold = response.get('quantity_sold') if isinstance(response, dict) else None
    if sold is None:
        return True
    telegram_booked = max(0, int(event.get('booked_seats') or 0) - eb_seats)
    return int(sold) + telegram_booked <= int(event['max_seats'])


async def reserve_on_eventbrite(context, event_id):
    """Called right after a Telegram booking, before confirming it: claims the seat on Eventbrite. False only when
    Eventbrite sold the last seat first (the caller must undo the booking); any other failure keeps the booking and
    leaves the poller's overbooking notice as the safety net."""
    event = get_event(event_id)
    if (not eventbrite_enabled() or not event or not event.get('eventbrite_event_id') or event.get('max_seats') is None
            or not event.get('eventbrite_ticket_class_id') or event.get('eventbrite_status') != 'live'):
        return True
    try:
        return await asyncio.to_thread(_reserve_blocking, event)
    except Exception as e:
        if is_gone(e):
            await unlink_deleted_eventbrite_event(context, event_id)
        else:
            logger.warning(f"Could not reserve the seat on Eventbrite for event #{event_id}: {e}")
        return True


def _push_content(event, include_dates=True):
    """Pushes name/summary/dates and the description page; returns a warning when the date had to be skipped."""
    eb_id, warning = event['eventbrite_event_id'], None
    try:
        payload = event_payload(event, include_dates=include_dates)
    except ValueError as e:
        payload = event_payload(event, include_dates=False)
        warning = DATE_NOT_UPDATED.format(id=event['id'], reason=e)
    update_event(eb_id, payload)
    current = get_event(event['id']) or event
    version = int(current.get('eventbrite_content_version') or 0) + 1
    set_eventbrite_info(event['id'], eventbrite_content_version=set_description(eb_id, description_modules(event), version))
    return warning


def _sync_blocking(event, content_changed, image_changed):
    warnings = []
    if event.get('status') == 'approved':
        _push_capacity(event)
    if content_changed:
        warning = _push_content(event)
        if warning:
            warnings.append(warning)
        # content_changed also covers a roleplay <-> board game switch: move the event to the right collection
        warning = _assign_collection(event, leave_other=True)
        if warning:
            warnings.append(warning)
    image_path = event.get('image_path')
    logo_error = None
    if image_changed and image_path and os.path.exists(image_path):
        try:
            update_event(event['eventbrite_event_id'], {"logo_id": upload_logo(image_path)})
        except Exception as e:
            logger.warning(f"Eventbrite logo upload failed for event #{event['id']}: {e}")
            logo_error = _failure_reason(e)
    return warnings, logo_error


async def sync_eventbrite(context, event, content_changed=False, image_changed=False):
    """Pushes capacity (always, for approved events), and content/logo when flagged. Never raises."""
    if not eventbrite_enabled() or not event or not event.get('eventbrite_event_id'):
        return
    # 'closed' = cancellation in progress: never reopen sales or rename it back
    if event.get('eventbrite_status') in ('canceled', 'draft', 'closed'):
        return
    try:
        warnings, logo_error = await asyncio.to_thread(_sync_blocking, event, content_changed, image_changed)
        for warning in warnings:
            await notify_admin(context, config.ADMIN_CHAT_ID, warning, event_id=event['id'])
        if logo_error:
            await notify_admin(context, config.ADMIN_CHAT_ID, format_eb_logo_not_updated(event['id'], logo_error),
                               reply_markup=_logo_retry_keyboard(event['id']), event_id=event['id'])
    except Exception as e:
        if is_gone(e):
            await unlink_deleted_eventbrite_event(context, event['id'])
            return
        logger.error(f"Eventbrite sync failed for event #{event.get('id')}: {e}")
        await notify_admin(context, config.ADMIN_CHAT_ID, format_eb_sync_failed(event.get('id'), e), event_id=event['id'])


def _retry_logo_blocking(event):
    update_event(event['eventbrite_event_id'], {"logo_id": upload_logo(event['image_path'])})


async def retry_logo_on_eventbrite(context, event_id, admin_chat_id):
    """Uploads the event's poster as the Eventbrite logo again (button after a failed upload)."""
    if not eventbrite_enabled():
        await notify_admin(context, admin_chat_id, NOT_CONFIGURED)
        return
    event = get_event(event_id)
    if not event or not event.get('eventbrite_event_id') or event.get('eventbrite_status') == 'canceled':
        await notify_admin(context, admin_chat_id, format_eb_not_active(event_id), event_id=event_id)
        return
    image_path = event.get('image_path')
    if not (image_path and os.path.exists(image_path)):
        await notify_admin(context, admin_chat_id, format_eb_no_image(event_id), event_id=event_id)
        return
    try:
        await asyncio.to_thread(_retry_logo_blocking, event)
    except Exception as e:
        logger.warning(f"Eventbrite logo retry failed for event #{event_id}: {e}")
        await notify_admin(context, admin_chat_id, format_eb_logo_not_uploaded(_failure_reason(e)),
                           reply_markup=_logo_retry_keyboard(event_id), event_id=event_id)
        return
    await notify_admin(context, admin_chat_id, format_eb_logo_uploaded(event_id), event_id=event_id)


# ---------------------------------------------------------------- cancel / reactivate

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


async def recreate_on_eventbrite(context, event_id, admin_chat_id):
    """Forgets a cancelled Eventbrite event and publishes a fresh one."""
    clear_eventbrite_info(event_id)
    await publish_event_to_eventbrite(context, event_id, admin_chat_id)


async def _run_eventbrite_publish(context, event_id, admin_chat_id, recreate):
    try:
        if recreate:
            await recreate_on_eventbrite(context, event_id, admin_chat_id)
        else:
            await publish_event_to_eventbrite(context, event_id, admin_chat_id)
    except Exception as e:
        logger.error(f"Background Eventbrite publish of event #{event_id} crashed: {e}")
    finally:
        runtime_state.eventbrite_publishing.discard(event_id)


async def start_eventbrite_publish(context, event_id, admin_chat_id, recreate=False):
    """Publishes (or re-creates) the event on Eventbrite in the background and returns at once, so the Telegram update
    that asked for it is not held up: the booking message of the discussion group is sent right away and gets the
    Eventbrite link when the publish ends (publish_event_to_eventbrite ends with update_event_messages). Failures are
    reported to the admins by the publish itself. One publish per event at a time."""
    if event_id in runtime_state.eventbrite_publishing:
        await notify_admin(context, admin_chat_id, format_eb_publish_in_progress(event_id), event_id=event_id)
        return
    runtime_state.eventbrite_publishing.add(event_id)
    task = asyncio.create_task(_run_eventbrite_publish(context, event_id, admin_chat_id, recreate))
    runtime_state.eventbrite_tasks.add(task)
    task.add_done_callback(runtime_state.eventbrite_tasks.discard)
