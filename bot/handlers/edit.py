import asyncio
import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from core import config
from core.db import update_event_field
from utils.image_utils import save_image_locally, delete_local_image
from utils.templates.edit import (
    EDIT_EVENT_ID_UNKNOWN, EDIT_IMAGE_MISSING, EDIT_IMAGE_SAVE_ERROR, EDIT_NO_REPLY, EDIT_PROMPT_EXPIRED, EDIT_PROMPT_MARKER,
)
from bot.common.auth import admin_only
from bot.common.parsing import extract_event_id_from_reply
from bot.handlers.albums import extract_image_bytes_from_update
from bot.keyboards import admin_card_keyboard
from bot.service.edits import EDIT_COMMAND_FIELDS, EditInputError, apply_edit
from bot.state import runtime_state

logger = logging.getLogger(__name__)


async def _edit_image(update, event_id, current_event, value):
    image_bytes = await extract_image_bytes_from_update(update)
    if not image_bytes:
        raise EditInputError(EDIT_IMAGE_MISSING)

    old_image_path = current_event.get("image_path")
    new_image_path = await asyncio.to_thread(save_image_locally, image_bytes, config.DATA_DIR, current_event.get("normalized_date"))
    if not new_image_path:
        raise EditInputError(EDIT_IMAGE_SAVE_ERROR)

    success = update_event_field(event_id, "image_path", new_image_path)
    if success and old_image_path and old_image_path != new_image_path:
        delete_local_image(old_image_path)
    return success


async def _resolve_edit_target(update, cmd, value):
    """Returns (event_id, target_msg); event_id is None after an explanatory reply has been sent."""
    reply_msg = update.message.reply_to_message

    if cmd == "/event_edit_image" and value.isdigit():
        event_id = int(value)
        target_msg = reply_msg if reply_msg and extract_event_id_from_reply(reply_msg) == event_id else None
        return event_id, target_msg

    if not reply_msg:
        await update.message.reply_text(EDIT_NO_REPLY)
        return None, None

    event_id = extract_event_id_from_reply(reply_msg)
    if not event_id:
        await update.message.reply_text(EDIT_EVENT_ID_UNKNOWN)
        return None, None
    return event_id, reply_msg


@admin_only()
async def event_edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_parts = (update.message.text or update.message.caption or "").split(maxsplit=1)
    if not text_parts:
        return
    cmd = text_parts[0].lower().split("@")[0]
    value = text_parts[1].strip() if len(text_parts) > 1 else ""

    if cmd not in EDIT_COMMAND_FIELDS:
        return

    event_id, target_msg = await _resolve_edit_target(update, cmd, value)
    if not event_id:
        return

    async def reply(text, parse_mode=None):
        await update.message.reply_text(text, **({"parse_mode": parse_mode} if parse_mode else {}))

    await apply_edit(
        context, event_id, cmd, value, reply, update.effective_user, target_msg=target_msg, update=update,
        editor=_edit_image if cmd == "/event_edit_image" else None,
    )


async def handle_edit_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The admin's answer to a ✏️ Modifica prompt (routed here by handle_admin_reply): edits that field.

    The prompt is remembered in memory with the admin card it belongs to; after a restart the card can no longer be
    redrawn, so the admin is asked to open the menu again.
    """
    prompt = update.message.reply_to_message
    entry = runtime_state.edit_prompts.pop(prompt.message_id, None)
    if not entry:
        await update.message.reply_text(EDIT_PROMPT_EXPIRED)
        return
    event_id, cmd, card = entry

    async def reply(text, parse_mode=None):
        await update.message.reply_text(text, **({"parse_mode": parse_mode} if parse_mode else {}))

    value = (update.message.text or "").strip()
    done = await apply_edit(context, event_id, cmd, value, reply, update.effective_user, target_msg=card,
                            update=update, card_keyboard=admin_card_keyboard)
    if not done:
        # Wrong value: keep the prompt open so the admin can answer it again
        runtime_state.edit_prompts[prompt.message_id] = entry


def is_edit_prompt(message):
    text = (message.text or message.caption or "") if message else ""
    return bool(re.search(re.escape(EDIT_PROMPT_MARKER) + r"\d+", text))
