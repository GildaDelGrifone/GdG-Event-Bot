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
    cancel_event,
    create_event,
    create_free_ticket_class,
    dashboard_url,
    description_modules,
    event_payload,
    event_start_end,
    eventbrite_enabled,
    fetch_active_orders,
    publish_event,
    refund_order,
    set_description,
    ticket_quantity,
    unpublish_event,
    update_event,
    upload_logo,
)
from core.eventbrite.tickets import update_ticket_quantity
from bot.common.messages import is_not_modified_error
from bot.keyboards import get_approved_event_keyboard

logger = logging.getLogger(__name__)

NOT_CONFIGURED = "❌ Eventbrite non configurato"
RATE_LIMIT_ERROR = "HIT_RATE_LIMIT"
DATE_NOT_UPDATED = "⚠️ Evento #{id}: data non aggiornata su Eventbrite ({reason})."


def _eb_seats_and_quantity(event):
    eb_seats = eventbrite_seat_count(event['id'])
    return eb_seats, ticket_quantity(event, eb_seats, config.EVENTBRITE_UNLIMITED_CAPACITY)


async def _notify(context, chat_id, text, reply_markup=None):
    if not chat_id:
        return
    try:
        await context.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=reply_markup, disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Could not send Eventbrite notice to admin chat: {e}")


async def _refresh_admin_card(context, event_id):
    """Swaps the buttons of the event's admin card; works from both the button and the command."""
    event = get_event(event_id)
    admin_message_id = event.get('admin_message_id') if event else None
    if not (admin_message_id and config.ADMIN_CHAT_ID):
        return
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=config.ADMIN_CHAT_ID, message_id=admin_message_id,
            reply_markup=get_approved_event_keyboard(event_id, event),
        )
    except Exception as e:
        if not is_not_modified_error(e) and "message to edit not found" not in str(e).lower():
            logger.warning(f"Could not refresh admin card of event #{event_id}: {e}")


def _recreate_keyboard(event_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎟️ Ricrea su Eventbrite", callback_data=f"eb_recreate_{event_id}")]])


def _full_event_message(event):
    max_seats = int(event['max_seats'])
    free = max(0, max_seats - int(event.get('booked_seats') or 0))
    return (
        f"❌ Eventbrite: l'evento non ha posti liberi ({free}/{max_seats}), non c'è nulla da prenotare su Eventbrite. "
        "Aggiorna i posti con /event_edit_seats e riprova con [🎟️ Pubblica su Eventbrite]."
    )


def _is_full(event):
    """Full = limited capacity with nothing left to sell. Unlimited (max_seats NULL) is never full; 0/0 Completo is."""
    if event.get('max_seats') is None:
        return False
    eb_seats, quantity = _eb_seats_and_quantity(event)
    return quantity - eb_seats <= 0


# ---------------------------------------------------------------- publish

def _publish_blocking(event, start_end):
    """Runs the publish steps in order, storing ids after each one so a failure can resume from the draft.
    Returns (eventbrite event JSON-ish dict with id/url, warnings)."""
    event_id = event['id']
    warnings = []
    eb_id, url = event.get('eventbrite_event_id'), event.get('eventbrite_url')

    if not eb_id:
        created = create_event(event_payload(event))
        eb_id, url = created['id'], created.get('url')
        set_eventbrite_info(event_id, eventbrite_event_id=eb_id, eventbrite_url=url,
                            eventbrite_status='draft', eventbrite_content_version=0)

    quantity = event.get('eventbrite_quantity_total')
    if not event.get('eventbrite_ticket_class_id'):
        _, quantity = _eb_seats_and_quantity(event)
        ticket_class = create_free_ticket_class(eb_id, quantity, start_end[1])
        set_eventbrite_info(event_id, eventbrite_ticket_class_id=ticket_class['id'], eventbrite_quantity_total=quantity)

    image_path = event.get('image_path')
    if image_path and os.path.exists(image_path):
        try:
            update_event(eb_id, {"logo_id": upload_logo(image_path)})
        except Exception as e:
            logger.warning(f"Eventbrite logo upload failed for event #{event_id}: {e}")
            warnings.append(f"⚠️ Logo non caricato su Eventbrite: {e}")

    version = int(event.get('eventbrite_content_version') or 0) + 1
    set_eventbrite_info(event_id, eventbrite_content_version=set_description(eb_id, description_modules(event), version))

    publish_event(eb_id)
    set_eventbrite_info(event_id, eventbrite_status='live', eventbrite_url=url, eventbrite_quantity_total=quantity)
    return {"id": eb_id, "url": url}, warnings


async def publish_event_to_eventbrite(context, event_id, admin_chat_id):
    """Publishes an approved event on Eventbrite (shared by the button and /event_publish_eventbrite). Idempotent."""
    if not eventbrite_enabled():
        await _notify(context, admin_chat_id, NOT_CONFIGURED)
        return

    event = get_event(event_id)
    if not event:
        await _notify(context, admin_chat_id, f"❌ Evento #{event_id} non trovato")
        return
    if event.get('status') != 'approved':
        await _notify(context, admin_chat_id, "❌ Eventbrite: l'evento deve essere pubblicato su Telegram (stato: approvato).")
        return

    eb_status = event.get('eventbrite_status')
    if event.get('eventbrite_event_id') and eb_status != 'draft':
        if eb_status == 'canceled':
            await _notify(context, admin_chat_id,
                          "ℹ️ L'evento era stato annullato su Eventbrite e non può essere riattivato.",
                          reply_markup=_recreate_keyboard(event_id))
        else:
            await _notify(context, admin_chat_id, f"ℹ️ Evento già pubblicato su Eventbrite: {event.get('eventbrite_url')}")
        return

    try:
        start_end = event_start_end(event)
    except ValueError as e:
        await _notify(context, admin_chat_id, f"❌ Eventbrite: {e}")
        return
    if not event.get('eventbrite_ticket_class_id') and _is_full(event):
        await _notify(context, admin_chat_id, _full_event_message(event))
        return

    try:
        result, warnings = await asyncio.to_thread(_publish_blocking, event, start_end)
    except Exception as e:
        logger.error(f"Eventbrite publish failed for event #{event_id}: {e}")
        await _notify(context, admin_chat_id,
                      f"❌ Eventbrite: pubblicazione fallita per #{event_id} ({e}). "
                      "Riprova con [🎟️ Pubblica su Eventbrite]: riprenderà dal punto in cui si è interrotta.")
        return

    for warning in warnings:
        await _notify(context, admin_chat_id, warning)
    await _notify(context, admin_chat_id, f"✅ Evento pubblicato su Eventbrite: {result['url']}")
    await _refresh_admin_card(context, event_id)
    # Imported here because bot.service.posts imports this module for sync_eventbrite
    from bot.service.posts import update_event_messages
    await update_event_messages(context, event_id)


# ---------------------------------------------------------------- sync

def _push_capacity(event, force=False):
    eb_id, tc_id = event['eventbrite_event_id'], event.get('eventbrite_ticket_class_id')
    if not tc_id:
        logger.warning(f"Event #{event['id']} has no Eventbrite ticket class; capacity not pushed.")
        return
    _, quantity = _eb_seats_and_quantity(event)
    if force or quantity != event.get('eventbrite_quantity_total'):
        update_ticket_quantity(eb_id, tc_id, quantity)
        set_eventbrite_info(event['id'], eventbrite_quantity_total=quantity)


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
    image_path = event.get('image_path')
    if image_changed and image_path and os.path.exists(image_path):
        update_event(event['eventbrite_event_id'], {"logo_id": upload_logo(image_path)})
    return warnings


async def sync_eventbrite(context, event, content_changed=False, image_changed=False):
    """Pushes capacity (always, for approved events), and content/logo when flagged. Never raises."""
    if not eventbrite_enabled() or not event or not event.get('eventbrite_event_id'):
        return
    if event.get('eventbrite_status') in ('canceled', 'draft'):
        return
    try:
        warnings = await asyncio.to_thread(_sync_blocking, event, content_changed, image_changed)
        for warning in warnings:
            await _notify(context, config.ADMIN_CHAT_ID, warning)
    except Exception as e:
        logger.error(f"Eventbrite sync failed for event #{event.get('id')}: {e}")
        await _notify(context, config.ADMIN_CHAT_ID, f"⚠️ Sync Eventbrite fallita per #{event.get('id')}: {e}")


# ---------------------------------------------------------------- cancel / reactivate

def _cancel_blocking(event):
    """Returns (outcome, refunded, failed): outcome is 'unpublished', 'canceled' or 'closed'; the counts are orders."""
    event_id, eb_id = event['id'], event['eventbrite_event_id']
    orders = fetch_active_orders(eb_id)
    eb_seats = sum(seats for _, seats in orders.values())

    if not orders:
        try:
            unpublish_event(eb_id)
            set_eventbrite_info(event_id, eventbrite_status='unpublished')
            return 'unpublished', 0, 0
        except EventbriteError as e:
            logger.warning(f"Eventbrite refused to unpublish event #{event_id} ({e.error}); trying to cancel it.")

    # Close sales at the number sold and flag the title
    cancelled = {**event, 'status': 'cancelled'}
    if event.get('eventbrite_ticket_class_id'):
        update_ticket_quantity(eb_id, event['eventbrite_ticket_class_id'], eb_seats)
        set_eventbrite_info(event_id, eventbrite_quantity_total=eb_seats)
    update_event(eb_id, event_payload(cancelled, include_dates=False))

    # The API cannot cancel an event with orders, so refund every order first (the admins confirmed this)
    refunded, failed = 0, 0
    pending = list(orders)
    for position, order_id in enumerate(pending):
        try:
            refund_order(order_id)
            refunded += 1
        except EventbriteError as e:
            logger.warning(f"Eventbrite refused to refund order {order_id} of event #{event_id} ({e.error}).")
            failed += 1
            if e.error == RATE_LIMIT_ERROR:
                failed += len(pending) - position - 1  # the rest was not attempted
                break

    if not failed:
        try:
            cancel_event(eb_id)
            set_eventbrite_info(event_id, eventbrite_status='canceled')
            return 'canceled', refunded, 0
        except EventbriteError as e:
            logger.warning(f"Eventbrite refused to cancel event #{event_id} ({e.error}); dashboard action needed.")
    set_eventbrite_info(event_id, eventbrite_status='closed')
    return 'closed', refunded, failed


async def cancel_on_eventbrite(context, event):
    """Mirrors a (confirmed) Telegram cancellation: unpublish when nobody booked, otherwise close sales, rename, refund
    every order and cancel."""
    if not eventbrite_enabled() or not event or not event.get('eventbrite_event_id'):
        return
    if event.get('eventbrite_status') in ('canceled', 'draft', 'unpublished', 'closed'):
        return

    event_id = event['id']
    try:
        outcome, refunded, failed = await asyncio.to_thread(_cancel_blocking, event)
    except Exception as e:
        logger.error(f"Eventbrite cancellation failed for event #{event_id}: {e}")
        await _notify(context, config.ADMIN_CHAT_ID, f"⚠️ Annullamento su Eventbrite fallito per #{event_id}: {e}")
        return

    if outcome == 'unpublished':
        await _notify(context, config.ADMIN_CHAT_ID, f"✅ Evento #{event_id} messo offline su Eventbrite (nessuna prenotazione).")
    elif outcome == 'canceled':
        refunds = f" ({refunded} prenotazioni rimborsate, i partecipanti sono stati avvisati via email)" if refunded else ""
        await _notify(context, config.ADMIN_CHAT_ID, f"✅ Evento #{event_id} annullato anche su Eventbrite{refunds}")
    else:
        url = dashboard_url(event['eventbrite_event_id'])
        if failed:
            text = (f"⚠️ Evento #{event_id}: {refunded} prenotazioni Eventbrite rimborsate, {failed} non rimborsabili via API. "
                    f"Gestiscile e annulla l'evento dalla dashboard (Eventbrite avviserà gli iscritti via email): {url}")
        else:
            text = (f"⚠️ Evento #{event_id}: {refunded} prenotazioni Eventbrite rimborsate, ma Eventbrite non permette di "
                    f"annullare l'evento via API. Annullalo dalla dashboard: {url}")
        await _notify(
            context, config.ADMIN_CHAT_ID, text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎟️ Apri dashboard Eventbrite", url=url)]]),
        )


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
        await _notify(context, config.ADMIN_CHAT_ID,
                      "ℹ️ L'evento era stato annullato su Eventbrite e non può essere riattivato.",
                      reply_markup=_recreate_keyboard(event_id))
        return
    if status not in ('unpublished', 'closed'):
        return

    try:
        warning = await asyncio.to_thread(_reactivate_blocking, event)
    except Exception as e:
        logger.error(f"Eventbrite reactivation failed for event #{event_id}: {e}")
        await _notify(context, config.ADMIN_CHAT_ID, f"⚠️ Riattivazione su Eventbrite fallita per #{event_id}: {e}")
        return
    if warning:
        await _notify(context, config.ADMIN_CHAT_ID, warning)
    await _notify(context, config.ADMIN_CHAT_ID, f"✅ Evento #{event_id} riattivato anche su Eventbrite")


async def recreate_on_eventbrite(context, event_id, admin_chat_id):
    """Forgets a cancelled Eventbrite event and publishes a fresh one."""
    clear_eventbrite_info(event_id)
    await publish_event_to_eventbrite(context, event_id, admin_chat_id)
