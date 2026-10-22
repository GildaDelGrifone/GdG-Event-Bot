import html
import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

from bot.common.auth import admin_only, describe_user
from bot.common.messages import command_argument, resolve_message, send_image_or_error
from bot.common.parsing import extract_event_id_from_reply
from core import config
from core.db import get_event
from utils.image_utils import create_story_image
from utils.templates.approval import (
    REGENERATE_STORY_PROGRESS, REGENERATE_STORY_USAGE, STORY_GENERATION_ERROR, STORY_SEND_ERROR,
    format_story_regenerated_caption,
)
from utils.templates.common import format_event_id_not_found_in_db

logger = logging.getLogger(__name__)


@admin_only()
async def event_regenerate_story_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await msg.reply_text(REGENERATE_STORY_USAGE)
        return

    event = get_event(event_id)
    if not event:
        await msg.reply_text(format_event_id_not_found_in_db(event_id))
        return

    logger.info(f"{describe_user(update.effective_user)} requested story regeneration for event #{event_id}.")
    status_msg = await msg.reply_text(REGENERATE_STORY_PROGRESS)

    story_image_path = create_story_image(event, event.get('image_path'), config.DATA_DIR)
    if story_image_path:
        await send_image_or_error(
            context.bot,
            msg.chat_id,
            story_image_path,
            caption=format_story_regenerated_caption(event_id, event.get('title')),
            error_text=STORY_SEND_ERROR,
        )
        try:
            await status_msg.delete()
        except Exception:
            pass
    else:
        try:
            await status_msg.edit_text(STORY_GENERATION_ERROR)
        except Exception:
            await msg.reply_text(STORY_GENERATION_ERROR)
