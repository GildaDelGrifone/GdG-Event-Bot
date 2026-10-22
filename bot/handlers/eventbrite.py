import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.common.auth import admin_only, describe_user
from bot.common.messages import command_argument, resolve_message
from bot.common.parsing import extract_event_id_from_reply
from bot.service.eventbrite import start_eventbrite_publish
from core.db import get_event
from utils.templates.common import format_event_id_not_found
from utils.templates.eventbrite import (
    PUBLISH_EVENTBRITE_CANCELLED, PUBLISH_EVENTBRITE_PENDING, PUBLISH_EVENTBRITE_USAGE,
)

logger = logging.getLogger(__name__)


@admin_only()
async def event_publish_eventbrite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Same as the [🎟️ Pubblica su Eventbrite] button; every other check lives in publish_event_to_eventbrite (which runs in the background)."""
    msg = resolve_message(update)
    if not msg:
        return

    reply_msg = msg.reply_to_message
    event_id = extract_event_id_from_reply(reply_msg) if reply_msg else None
    if not event_id:
        arg = command_argument(msg)
        if arg and arg.strip().isdigit():
            event_id = int(arg.strip())

    if not event_id:
        await msg.reply_text(PUBLISH_EVENTBRITE_USAGE)
        return

    event = get_event(event_id)
    if not event:
        await msg.reply_text(format_event_id_not_found(event_id))
        return
    if event.get('status') == 'pending':
        await msg.reply_text(PUBLISH_EVENTBRITE_PENDING)
        return
    if event.get('status') == 'cancelled':
        await msg.reply_text(PUBLISH_EVENTBRITE_CANCELLED)
        return

    logger.info(f"{describe_user(update.effective_user)} requested Eventbrite publication of event #{event_id}.")
    await start_eventbrite_publish(context, event_id, msg.chat_id)
