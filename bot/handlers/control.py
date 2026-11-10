import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.common.auth import admin_only, describe_user
from core import config
from core.eventbrite import eventbrite_enabled, eventbrite_venue_ids
from bot.keyboards import get_venue_keyboard
from bot.service.eventbrite import venue_name
from bot.state import reset_persisted_state, runtime_state, set_persisted
from utils.templates.control import (
    BOT_PAUSED_TEXT, BOT_RESUMED_TEXT, CHOOSE_VENUE_TEXT, EVENTBRITE_NOT_CONFIGURED_SHORT_TEXT,
    EVENTBRITE_NOTIFICATIONS_OFF_TEXT, EVENTBRITE_NOTIFICATIONS_ON_TEXT, EVENTBRITE_ONLY_OFF_TEXT, EVENTBRITE_ONLY_ON_TEXT,
    EVENTBRITE_ONLY_UNAVAILABLE_TEXT, SETTINGS_CLEAR_FAILED_TEXT, SETTINGS_CLEARED_TEXT, SINGLE_VENUE_TEXT, format_bot_status,
)

logger = logging.getLogger(__name__)


@admin_only()
async def bot_pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_persisted("is_paused", True)
    logger.info(f"{describe_user(update.effective_user)} paused bot execution.")
    await update.message.reply_text(BOT_PAUSED_TEXT, parse_mode="Markdown")


@admin_only()
async def bot_resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_persisted("is_paused", False)
    logger.info(f"{describe_user(update.effective_user)} resumed bot execution.")
    await update.message.reply_text(BOT_RESUMED_TEXT, parse_mode="Markdown")


@admin_only()
async def bot_eventbrite_only_toggle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eventbrite_enabled():
        await update.message.reply_text(EVENTBRITE_ONLY_UNAVAILABLE_TEXT)
        return
    set_persisted("eventbrite_only", not runtime_state.eventbrite_only)
    state = "ON" if runtime_state.eventbrite_only else "OFF"
    logger.info(f"{describe_user(update.effective_user)} turned Eventbrite-only mode {state}.")
    if runtime_state.eventbrite_only:
        text = EVENTBRITE_ONLY_ON_TEXT
    else:
        text = EVENTBRITE_ONLY_OFF_TEXT
    await update.message.reply_text(text)


@admin_only()
async def bot_eb_notif_toggle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eventbrite_enabled():
        await update.message.reply_text(EVENTBRITE_NOT_CONFIGURED_SHORT_TEXT)
        return
    enabled = not runtime_state.eventbrite_booking_notifications
    set_persisted("eventbrite_booking_notifications", enabled)
    logger.info(f"{describe_user(update.effective_user)} turned Eventbrite booking notifications {'ON' if enabled else 'OFF'}.")
    await update.message.reply_text(EVENTBRITE_NOTIFICATIONS_ON_TEXT if enabled else EVENTBRITE_NOTIFICATIONS_OFF_TEXT)


@admin_only()
async def bot_settings_clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleared = reset_persisted_state()
    logger.info(f"{describe_user(update.effective_user)} cleared the persisted settings.")
    header = SETTINGS_CLEARED_TEXT if cleared else SETTINGS_CLEAR_FAILED_TEXT
    await update.message.reply_text(f"{header}\n\n{await _status_text()}")


def current_venue_id():
    """The venue new Eventbrite events get: the /bot_eventbrite_venue pick, else the default."""
    picked = runtime_state.eventbrite_venue
    return picked if picked in eventbrite_venue_ids() else config.EVENTBRITE_VENUE_ID


@admin_only()
async def bot_eventbrite_venue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not eventbrite_enabled():
        await update.message.reply_text(EVENTBRITE_NOT_CONFIGURED_SHORT_TEXT)
        return
    venue_ids = eventbrite_venue_ids()
    if len(venue_ids) < 2:
        await update.message.reply_text(SINGLE_VENUE_TEXT)
        return
    venues = [(venue_id, await asyncio.to_thread(venue_name, venue_id)) for venue_id in venue_ids]
    await update.message.reply_text(
        CHOOSE_VENUE_TEXT,
        reply_markup=get_venue_keyboard(venues, current_venue_id(), config.EVENTBRITE_VENUE_ID),
    )


@admin_only()
async def bot_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"{describe_user(update.effective_user)} requested bot status.")
    await update.message.reply_text(await _status_text())


async def _status_text():
    venue = notifications = None
    if eventbrite_enabled():
        notifications = runtime_state.eventbrite_booking_notifications
        if len(eventbrite_venue_ids()) > 1:
            venue = await asyncio.to_thread(venue_name, current_venue_id())
    return format_bot_status(runtime_state.is_paused, runtime_state.eventbrite_only, venue, notifications)
