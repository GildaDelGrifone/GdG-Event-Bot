import asyncio
import logging

from core import config
from core.eventbrite import eventbrite_venue_ids
from bot.common.auth import describe_user
from bot.keyboards import get_venue_keyboard
from bot.service.eventbrite import venue_name
from bot.state import runtime_state

logger = logging.getLogger(__name__)


async def handle_venue_close(query, context, payload):
    """`[❌ Chiudi]` button of /bot_eventbrite_venue: removes the picker message."""
    await query.answer("Chiuso.")
    try:
        await query.message.delete()
    except Exception:
        pass


async def handle_venue_pick(query, context, payload):
    """`[📍 sede]` button of /bot_eventbrite_venue: sets the venue used for the events published from now on."""
    if not (config.ADMIN_CHAT_ID and str(query.message.chat_id) == str(config.ADMIN_CHAT_ID)):
        await query.answer()
        return
    venue_ids = eventbrite_venue_ids()
    if payload not in venue_ids:
        await query.answer("Sede non più configurata.", show_alert=True)
        return
    runtime_state.eventbrite_venue = payload
    logger.info(f"{describe_user(query.from_user)} set the Eventbrite venue for new events to {payload}.")
    venues = [(venue_id, await asyncio.to_thread(venue_name, venue_id)) for venue_id in venue_ids]
    await query.answer("Sede aggiornata")
    await query.edit_message_text(
        f"📍 Sede Eventbrite per i nuovi eventi: {dict(venues)[payload]}",
        reply_markup=get_venue_keyboard(venues, payload, config.EVENTBRITE_VENUE_ID),
    )
