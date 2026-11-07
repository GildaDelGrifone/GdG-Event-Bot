"""Day-of reminder DMs to the Telegram users booked to today's events (registered by main.post_init)."""
import asyncio
import logging
from datetime import datetime

from telegram.error import Forbidden, TelegramError

from core.db import get_approved_events_for_date, get_reservations_for_event
from utils.templates.booking import format_event_reminder
from utils.templates.common import format_event_title_link
from bot.keyboards import get_reminder_keyboard

logger = logging.getLogger(__name__)

# Pause between two DMs, well under Telegram's ~30 messages/second
SEND_INTERVAL = 0.1


async def send_event_reminders(bot, today=None):
    """DMs each Telegram user booked to an approved event of today, once per event.

    Users who never opened a private chat with the bot cannot be reached (Forbidden): they are skipped.
    Returns the number of reminders delivered.
    """
    day = (today or datetime.now()).strftime("%d-%m-%Y")
    sent = skipped = 0
    for event in get_approved_events_for_date(day):
        event_link = format_event_title_link(event)
        for reservation in get_reservations_for_event(event['id']):
            user_id, seats = reservation.get('user_id'), int(reservation.get('seats_booked') or 0)
            if reservation.get('source') == 'eventbrite' or not user_id or seats <= 0:
                continue
            try:
                await bot.send_message(
                    chat_id=user_id, text=format_event_reminder(event_link, event.get('date'), seats),
                    reply_markup=get_reminder_keyboard(event), parse_mode="HTML", disable_web_page_preview=True,
                )
                sent += 1
            except Forbidden:
                skipped += 1
            except TelegramError as e:
                skipped += 1
                logger.warning(f"Reminder: could not DM user {user_id} for event #{event['id']}: {e}")
            await asyncio.sleep(SEND_INTERVAL)
    if sent or skipped:
        logger.info(f"Reminder: {sent} reminders sent for {day}, {skipped} users not reachable by DM.")
    return sent
