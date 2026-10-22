"""Keeping a published Eventbrite event in step with Telegram: seat capacity, content, logo, and claiming a seat on booking."""
import asyncio
import logging
import os

from core import config
from core.db import get_event, set_eventbrite_info
from core.eventbrite import (
    EventbriteError, description_modules, event_payload, event_start_end, eventbrite_enabled, set_description,
    update_event, upload_logo,
)
from core.eventbrite.tickets import update_ticket_capacity
from utils.templates.eventbrite import (
    DATE_NOT_UPDATED, NOT_CONFIGURED, format_eb_logo_not_updated, format_eb_logo_not_uploaded, format_eb_logo_uploaded,
    format_eb_no_image, format_eb_not_active, format_eb_sync_failed,
)
from bot.service.eventbrite.common import (
    _assign_collection, _eb_seats_and_quantity, _failure_reason, _logo_retry_keyboard, is_gone, notify_admin,
    unlink_deleted_eventbrite_event,
)

logger = logging.getLogger(__name__)


def _update_capacity(event, eb_seats, quantity):
    """Pushes the ticket total (closing sales when no seat is left, see update_ticket_capacity); returns the response."""
    try:
        sales_end = event_start_end(event)[1]
    except ValueError:  # past or undated event: leave the sales end alone
        sales_end = None
    return update_ticket_capacity(event['eventbrite_event_id'], event['eventbrite_ticket_class_id'], quantity, eb_seats, sales_end)


def _push_capacity(event, force=False):
    tc_id = event.get('eventbrite_ticket_class_id')
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
