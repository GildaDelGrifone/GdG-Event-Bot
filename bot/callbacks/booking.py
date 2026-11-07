import logging

from telegram.error import TelegramError

from core.db import get_event
from bot.keyboards import is_event_full
from bot.service.booking import handle_seat_booking, handle_seat_unbooking, handle_waitlist_join
from utils.templates.common import POPUP_EVENT_NOT_FOUND

logger = logging.getLogger(__name__)


async def handle_full(query, context, payload):
    """The "⏳ Lista d'attesa" button: book if a seat freed up since the keyboard was rendered, else join the queue."""
    event_id = int(payload)
    event = get_event(event_id)
    if not event:
        try:
            await query.answer(POPUP_EVENT_NOT_FOUND, show_alert=True)
        except TelegramError as e:
            logger.debug(f"Could not answer callback query: {e}")
        return

    if not is_event_full(event) and not event.get('waitlist_count'):
        await handle_seat_booking(event_id, query.from_user, query, context)
        return
    await handle_waitlist_join(event_id, query.from_user, query, context)


async def handle_book(query, context, payload):
    event_id = int(payload)
    event = get_event(event_id)
    if event and event.get('waitlist_count'):
        # A seat was freed but people are queued for it: an old ➕ Prenota button must not jump the queue
        await handle_waitlist_join(event_id, query.from_user, query, context)
        return
    await handle_seat_booking(event_id, query.from_user, query, context)


async def handle_unbook(query, context, payload):
    await handle_seat_unbooking(int(payload), query.from_user, query, context)
