"""✏️ Modifica on the admin card: field buttons that ask for the new value (ForceReply) and a type toggle.

The admin's answer is handled by bot.handlers.edit.handle_edit_reply (routed from handle_admin_reply), which uses
the same bot.service.edits.apply_edit as /event_edit_*.
"""
import logging

from telegram import ForceReply
from telegram.error import TelegramError

from core.db import get_event
from utils.templates.common import POPUP_EVENT_NOT_FOUND
from utils.templates.edit import EDIT_MENU_FIELDS, format_edit_prompt
from bot.common.auth import describe_user
from bot.common.messages import is_not_modified_error
from bot.keyboards import admin_card_keyboard, get_edit_menu_keyboard
from bot.service.edits import EDIT_COMMAND_FIELDS, apply_edit
from bot.state import remember_edit_prompt

logger = logging.getLogger(__name__)

_FIELDS_BY_KEY = {key: (label, cmd, hint) for key, label, cmd, hint in EDIT_MENU_FIELDS}


async def _event_or_popup(query, event_id):
    event = get_event(event_id)
    if not event:
        await query.answer(POPUP_EVENT_NOT_FOUND, show_alert=True)
    return event


async def _set_card_keyboard(query, keyboard):
    try:
        await query.edit_message_reply_markup(reply_markup=keyboard)
    except TelegramError as e:
        if not is_not_modified_error(e):
            logger.warning(f"Could not change the admin card buttons: {e}")


async def handle_edit_menu(query, context, payload):
    event = await _event_or_popup(query, int(payload))
    if not event:
        return
    await query.answer()
    await _set_card_keyboard(query, get_edit_menu_keyboard(event))


async def handle_edit_back(query, context, payload):
    event = await _event_or_popup(query, int(payload))
    if not event:
        return
    await query.answer()
    await _set_card_keyboard(query, admin_card_keyboard(event))


async def handle_edit_field(query, context, payload):
    """Puts the card's normal buttons back and asks for the new value with a ForceReply prompt under the card."""
    event_id_str, _, key = payload.partition("_")
    event = await _event_or_popup(query, int(event_id_str))
    if not event or key not in _FIELDS_BY_KEY:
        return
    label, cmd, hint = _FIELDS_BY_KEY[key]
    await query.answer()
    await _set_card_keyboard(query, admin_card_keyboard(event))
    logger.info(f"{describe_user(query.from_user)} opened the edit prompt for '{key}' of event #{event['id']}.")
    prompt = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=format_edit_prompt(event['id'], label, event.get(EDIT_COMMAND_FIELDS[cmd]), hint),
        reply_to_message_id=query.message.message_id,
        reply_markup=ForceReply(selective=True),
    )
    remember_edit_prompt(prompt.message_id, event['id'], cmd, query.message)


async def handle_edit_type(query, context, payload):
    """🎲 Tipo: flips roleplay/board game at once; the card stays on the edit menu with the new label."""
    event_id = int(payload)
    if not await _event_or_popup(query, event_id):
        return

    async def reply(text, parse_mode=None):
        await query.answer(text)

    await apply_edit(context, event_id, "/event_edit_type", "", reply, query.from_user,
                     target_msg=query.message, card_keyboard=get_edit_menu_keyboard)
