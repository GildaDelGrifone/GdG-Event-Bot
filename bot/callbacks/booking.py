import logging

from core.db import get_event
from bot.keyboards import is_event_full
from bot.service.booking import handle_seat_booking, handle_seat_unbooking
from bot.service.posts import update_event_messages

logger = logging.getLogger(__name__)


async def handle_full(query, context, payload):
    """The "🚫 Esauriti" button: book anyway if a seat freed up since the keyboard was rendered."""
    event_id = int(payload)
    event = get_event(event_id)
    if not event:
        try:
            await query.answer("Evento non trovato.", show_alert=True)
        except Exception:
            pass
        return

    if not is_event_full(event):
        await handle_seat_booking(event_id, query.from_user, query, context)
        return

    logger.warning(f"User {query.from_user.id} (@{query.from_user.username}) attempted to book full event #{event_id}.")
    try:
        await query.answer("I posti per questo tavolo sono esauriti!", show_alert=True)
    except Exception:
        pass
    await update_event_messages(context, event_id, event=event, current_query=query)


async def handle_book(query, context, payload):
    await handle_seat_booking(int(payload), query.from_user, query, context)


async def handle_unbook(query, context, payload):
    await handle_seat_unbooking(int(payload), query.from_user, query, context)
