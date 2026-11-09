import logging

from telegram.error import TelegramError

from core import config
from core.db import get_event, get_user_upcoming_reservations
from bot.keyboards import accepts_waitlist, is_event_full
from bot.service.booking import handle_seat_booking, handle_seat_unbooking, handle_waitlist_join
from utils.templates.booking import POPUP_TABLE_FULL, format_seat_released_from_dm
from utils.templates.common import POPUP_EVENT_NOT_FOUND, format_event_title_link
from utils.templates.public import EVENT_MINE_NONE
from bot.service.listings import render_my_bookings

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
    if not accepts_waitlist(event):
        try:
            await query.answer(POPUP_TABLE_FULL, show_alert=True)
        except TelegramError as e:
            logger.debug(f"Could not answer callback query: {e}")
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


async def handle_dm_unbook(query, context, payload):
    """[➖ Libera un posto] on the day-of reminder DM: frees one seat; the DM then says so, without the button."""
    event_id = int(payload)
    if not await handle_seat_unbooking(event_id, query.from_user, query, context, in_private=True):
        return
    event = get_event(event_id)
    if not event:
        return
    try:
        await query.edit_message_text(
            f"{query.message.text_html}\n\n{format_seat_released_from_dm(format_event_title_link(event))}",
            parse_mode="HTML", disable_web_page_preview=True,
        )
    except TelegramError as e:
        logger.debug(f"Could not update the reminder DM: {e}")


async def handle_mine_unbook(query, context, payload):
    """[➖ title] under /event_mine in a private chat: frees one seat and redraws the list in place."""
    user = query.from_user
    if not await handle_seat_unbooking(int(payload), user, query, context, in_private=True):
        return
    events = get_user_upcoming_reservations(user.id, user.username)
    bot_username = getattr(context.bot, "username", None) or config.TELEGRAM_BOT_USERNAME
    view = render_my_bookings(events, bot_username) if events else (EVENT_MINE_NONE, None)
    if not view:
        return
    text, keyboard = view
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True)
    except TelegramError as e:
        logger.debug(f"Could not redraw /event_mine: {e}")
