"""Publishing an approved event on Eventbrite (draft -> ticket -> logo -> description -> live), in the background."""
import asyncio
import logging
import os

from core import config
from core.db import clear_eventbrite_info, get_event, set_eventbrite_info
from core.eventbrite import (
    EventbriteError, create_event, create_free_ticket_class, description_modules, event_payload, event_start_end,
    eventbrite_enabled, eventbrite_venue_ids, publish_event, set_description, update_event, upload_logo,
)
from bot.state import runtime_state
from utils.templates.common import format_event_id_not_found
from utils.templates.eventbrite import (
    EVENTBRITE_CANCELLED_CANNOT_REACTIVATE, EVENTBRITE_MUST_BE_APPROVED, NOT_CONFIGURED, format_eb_already_published,
    format_eb_error, format_eb_logo_not_uploaded, format_eb_publish_failed, format_eb_publish_in_progress,
    format_eb_published,
)
from bot.service.eventbrite.common import (
    _assign_collection, _eb_seats_and_quantity, _failure_reason, _is_full, _logo_retry_keyboard, _recreate_keyboard,
    is_gone, notify_admin, refresh_admin_card, venue_name,
)

logger = logging.getLogger(__name__)


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
