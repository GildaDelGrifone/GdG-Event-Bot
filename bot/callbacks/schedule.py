import logging

from telegram.error import TelegramError

from core.db import get_scheduled_event, update_scheduled_event_days, delete_scheduled_event
from utils.templates.common import POPUP_CLOSED
from utils.templates.reposts import (
    POPUP_SCHEDULE_DELETED, POPUP_SCHEDULE_NOT_FOUND, SCHEDULE_DELETED_TEXT, format_schedule_day_toggled,
    format_schedule_repost_message,
)
from bot.common.messages import is_not_modified_error
from bot.keyboards import SCHEDULE_DAY_NAMES, get_schedule_repost_keyboard

logger = logging.getLogger(__name__)


async def handle_toggle_day(query, context, payload):
    parts = payload.split("_")
    if len(parts) < 2:
        return
    scheduled_id = int(parts[0])
    day_key = parts[1].lower()
    target_day = SCHEDULE_DAY_NAMES.get(day_key, day_key.capitalize())

    sched_ev = get_scheduled_event(scheduled_id)
    if not sched_ev:
        await query.answer(POPUP_SCHEDULE_NOT_FOUND, show_alert=True)
        return

    current_days = sched_ev.get('schedule_days') or []
    remaining = [d for d in current_days if d.strip().lower() != target_day.lower()]
    if len(remaining) < len(current_days):
        current_days = remaining
        await query.answer(format_schedule_day_toggled(target_day, active=False))
    else:
        current_days.append(target_day)
        await query.answer(format_schedule_day_toggled(target_day, active=True))

    update_scheduled_event_days(scheduled_id, current_days)
    sched_ev['schedule_days'] = current_days

    new_text = format_schedule_repost_message(sched_ev)
    keyboard = get_schedule_repost_keyboard(scheduled_id, current_days)
    try:
        if query.message.photo:
            await query.edit_message_caption(caption=new_text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await query.edit_message_text(text=new_text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error updating schedule message on toggle: {e}")


async def handle_delete_schedule(query, context, payload):
    delete_scheduled_event(int(payload))
    await query.answer(POPUP_SCHEDULE_DELETED)
    text = SCHEDULE_DELETED_TEXT
    try:
        if query.message.photo:
            await query.edit_message_caption(caption=text, reply_markup=None)
        else:
            await query.edit_message_text(text=text, reply_markup=None)
    except TelegramError as e:
        if not is_not_modified_error(e):
            logger.warning(f"Could not edit deleted schedule card: {e}")


async def handle_close_schedule(query, context, payload):
    await query.answer(POPUP_CLOSED)
    try:
        await query.message.delete()
    except TelegramError as e:
        logger.debug(f"Could not delete schedule card: {e}")
