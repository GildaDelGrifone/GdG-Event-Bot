import asyncio
import logging

from telegram.error import TelegramError

from core import config
from core.eventbrite import eventbrite_venue_ids
from bot.common.auth import describe_user
from bot.keyboards import get_venue_keyboard
from bot.service.eventbrite import venue_name
from bot.state import runtime_state
from utils.templates.common import POPUP_CLOSED
from utils.templates.control import POPUP_VENUE_GONE, POPUP_VENUE_UPDATED, format_venue_selected

logger = logging.getLogger(__name__)


async def handle_venue_close(query, context, payload):
    """`[❌ Chiudi]` button of /bot_eventbrite_venue: removes the picker message."""
    await query.answer(POPUP_CLOSED)
    try:
        await query.message.delete()
    except TelegramError as e:
        logger.debug(f"Could not delete venue picker: {e}")


async def handle_venue_pick(query, context, payload):
    """`[📍 sede]` button of /bot_eventbrite_venue: sets the venue used for the events published from now on."""
    if not (config.ADMIN_CHAT_ID and str(query.message.chat_id) == str(config.ADMIN_CHAT_ID)):
        await query.answer()
        return
    venue_ids = eventbrite_venue_ids()
    if payload not in venue_ids:
        await query.answer(POPUP_VENUE_GONE, show_alert=True)
        return
    runtime_state.eventbrite_venue = payload
    logger.info(f"{describe_user(query.from_user)} set the Eventbrite venue for new events to {payload}.")
    venues = [(venue_id, await asyncio.to_thread(venue_name, venue_id)) for venue_id in venue_ids]
    await query.answer(POPUP_VENUE_UPDATED)
    await query.edit_message_text(
        format_venue_selected(dict(venues)[payload]),
        reply_markup=get_venue_keyboard(venues, payload, config.EVENTBRITE_VENUE_ID),
    )
