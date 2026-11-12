"""/event_cancel, /event_cancel_eventbrite and /event_delete: the [❌ Annulla Evento], [🚫 Annulla su Eventbrite] and
[🗑️ Elimina evento] buttons as commands. Like the buttons they only ask for confirmation: the reply carries the same
confirmation keyboard (marked as coming from a command), and bot.callbacks.events does the work."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.common.auth import admin_only, describe_user
from bot.common.messages import resolve_message
from bot.common.parsing import resolve_event_id
from bot.keyboards import (
    get_cancel_confirmation_keyboard, get_delete_confirmation_keyboard, get_eventbrite_cancel_confirmation_keyboard,
)
from bot.service.eventbrite import eventbrite_cancellable
from core.db import get_event
from utils.templates.approval import (
    CANCEL_ONLY_APPROVED, EVENT_CANCEL_EVENTBRITE_USAGE, EVENT_CANCEL_USAGE, EVENT_DELETE_USAGE,
    POPUP_ALREADY_CANCELLED, POPUP_DELETE_EB_ORDERS_OPEN, POPUP_DELETE_ONLY_CANCELLED,
    POPUP_NOTHING_TO_CANCEL_ON_EVENTBRITE, format_cancel_prompt, format_delete_prompt, format_eb_cancel_prompt,
)
from utils.templates.common import format_event_id_not_found

logger = logging.getLogger(__name__)


async def _load_event(update, usage):
    """(message, event), or (message, None) after the usage / not-found reply."""
    msg = resolve_message(update)
    if not msg:
        return None, None
    event_id = resolve_event_id(msg)
    if not event_id:
        await msg.reply_text(usage)
        return msg, None
    event = get_event(event_id)
    if not event:
        await msg.reply_text(format_event_id_not_found(event_id))
    return msg, event


async def _ask(update, msg, event, action, text, keyboard):
    logger.info(f"{describe_user(update.effective_user)} asked to {action} event #{event['id']} "
                "by command (confirmation requested).")
    await msg.reply_text(text, reply_markup=keyboard)


@admin_only()
async def event_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Same as [❌ Annulla Evento]."""
    msg, event = await _load_event(update, EVENT_CANCEL_USAGE)
    if not event:
        return
    if event.get('status') != 'approved':
        await msg.reply_text(POPUP_ALREADY_CANCELLED if event.get('status') == 'cancelled' else CANCEL_ONLY_APPROVED)
        return
    await _ask(update, msg, event, "cancel", format_cancel_prompt(event),
               get_cancel_confirmation_keyboard(event['id'], from_command=True))


@admin_only()
async def event_cancel_eventbrite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Same as [🚫 Annulla su Eventbrite]: the Telegram event stays active."""
    msg, event = await _load_event(update, EVENT_CANCEL_EVENTBRITE_USAGE)
    if not event:
        return
    if not eventbrite_cancellable(event):
        await msg.reply_text(POPUP_NOTHING_TO_CANCEL_ON_EVENTBRITE)
        return
    await _ask(update, msg, event, "cancel on Eventbrite only", format_eb_cancel_prompt(event),
               get_eventbrite_cancel_confirmation_keyboard(event['id'], from_command=True))


@admin_only()
async def event_delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Same as [🗑️ Elimina evento]: cancelled events only."""
    msg, event = await _load_event(update, EVENT_DELETE_USAGE)
    if not event:
        return
    if event.get('status') != 'cancelled':
        await msg.reply_text(POPUP_DELETE_ONLY_CANCELLED)
        return
    if event.get('eventbrite_event_id') and event.get('eventbrite_status') == 'closed':
        await msg.reply_text(POPUP_DELETE_EB_ORDERS_OPEN)
        return
    await _ask(update, msg, event, "delete", format_delete_prompt(event),
               get_delete_confirmation_keyboard(event['id'], from_command=True))
