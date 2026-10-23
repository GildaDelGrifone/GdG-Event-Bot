import logging

from telegram.error import TelegramError

from core.db import (
    get_scheduled_event, update_scheduled_event_advance_days, update_scheduled_event_days, delete_scheduled_event,
)
from core.db.scheduled import MAX_ADVANCE_DAYS
from utils.templates.common import POPUP_CLOSED
from utils.templates.reposts import (
    POPUP_SCHEDULE_DELETED, POPUP_SCHEDULE_NOT_FOUND, SCHEDULE_DELETED_TEXT, format_schedule_advance_popup,
    format_schedule_day_toggled, format_schedule_repost_message,
)
from bot.common.messages import edit_card, is_not_modified_error
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
    keyboard = get_schedule_repost_keyboard(scheduled_id, current_days, sched_ev.get('advance_days'))
    try:
        await edit_card(query, new_text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error updating schedule message on toggle: {e}")


async def handle_advance_days(query, context, payload):
    parts = payload.split("_")
    if len(parts) < 2:
        return
    scheduled_id = int(parts[0])
    action = parts[1]

    sched_ev = get_scheduled_event(scheduled_id)
    if not sched_ev:
        await query.answer(POPUP_SCHEDULE_NOT_FOUND, show_alert=True)
        return

    current = sched_ev.get('advance_days') or 0
    step = {"inc": 1, "dec": -1}.get(action, 0)
    new_value = max(0, min(MAX_ADVANCE_DAYS, current + step))
    if new_value == current:
        await query.answer(format_schedule_advance_popup(current))
        return

    update_scheduled_event_advance_days(scheduled_id, new_value)
    sched_ev['advance_days'] = new_value
    await query.answer(format_schedule_advance_popup(new_value))
    try:
        await edit_card(
            query, format_schedule_repost_message(sched_ev),
            reply_markup=get_schedule_repost_keyboard(scheduled_id, sched_ev.get('schedule_days'), new_value),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Error updating schedule message on advance change: {e}")


async def handle_delete_schedule(query, context, payload):
    delete_scheduled_event(int(payload))
    await query.answer(POPUP_SCHEDULE_DELETED)
    text = SCHEDULE_DELETED_TEXT
    try:
        await edit_card(query, text, reply_markup=None)
    except TelegramError as e:
        if not is_not_modified_error(e):
            logger.warning(f"Could not edit deleted schedule card: {e}")


async def handle_close_schedule(query, context, payload):
    await query.answer(POPUP_CLOSED)
    try:
        await query.message.delete()
    except TelegramError as e:
        logger.debug(f"Could not delete schedule card: {e}")
