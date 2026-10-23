"""Helpers shared by the Eventbrite flows: admin notices and card refresh, venue names, collections, unlinking deleted events."""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from core.db import clear_eventbrite_info, eventbrite_seat_count, get_event
from core.eventbrite import (
    EventbriteError, add_event_to_collection, get_venue, remove_event_from_collection, ticket_quantity,
)
from core.eventbrite.media import short_reason
from bot.common.messages import is_not_modified_error
from bot.keyboards import get_approved_event_keyboard, get_cancelled_event_keyboard
from bot.state import runtime_state
from utils.templates.eventbrite import format_eb_collection_warning, format_eb_link_removed
from utils.templates.keyboards import BUTTON_EB_RECREATE, BUTTON_EB_RETRY_LOGO

logger = logging.getLogger(__name__)


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
