"""[🔔 Riattiva annunci] buttons: lift the silencing the Eventbrite churn detection put on an attendee name.

`ebmute_clear_<id>` sits under the churn alert (the alert is edited); `ebmute_panel_<id>` sits in the 👥 Gestisci
Iscritti panel (the panel is redrawn)."""
import html
import logging

from telegram.error import TelegramError

from core import config
from core.db import get_event, get_eventbrite_mute, unmute_eventbrite
from bot.callbacks.subscribers import _render_panel
from bot.common.auth import describe_user
from bot.common.messages import is_not_modified_error
from bot.service.eventbrite_poll import forget_churn
from utils.templates.eventbrite import POPUP_EB_UNMUTE_GONE, POPUP_EB_UNMUTED, format_eb_unmuted

logger = logging.getLogger(__name__)


def _admin_label(user):
    if getattr(user, "username", None):
        return f"@{user.username}"
    return getattr(user, "full_name", None) or "un admin"


async def _unmute(query, payload):
    """Deletes the mute and resets the name's release history; returns the mute, or None (popup already answered)."""
    if not (config.ADMIN_CHAT_ID and str(query.message.chat_id) == str(config.ADMIN_CHAT_ID)):
        await query.answer()
        return None
    try:
        mute_id = int(payload)
    except ValueError:
        await query.answer()
        return None
    mute = get_eventbrite_mute(mute_id)
    if not mute or not unmute_eventbrite(mute_id):
        await query.answer(POPUP_EB_UNMUTE_GONE, show_alert=True)
        return None
    forget_churn(mute['event_id'], mute['name'])  # otherwise the next release would silence the name again at once
    logger.info(f'{describe_user(query.from_user)} unmuted Eventbrite announcements for "{mute["name"]}" '
                f"on event #{mute['event_id']}.")
    await query.answer(POPUP_EB_UNMUTED)
    return mute


async def handle_mute_clear(query, context, payload):
    """Button under the churn alert: unmutes and marks the alert as handled (buttons removed)."""
    if not await _unmute(query, payload):
        return
    message = query.message
    text_html = getattr(message, "text_html", None)
    body = text_html if isinstance(text_html, str) else html.escape(message.text or "")
    try:
        await query.edit_message_text(
            text=f"{body}\n\n{html.escape(format_eb_unmuted(_admin_label(query.from_user)))}",
            parse_mode="HTML", reply_markup=None, disable_web_page_preview=True,
        )
    except TelegramError as e:
        logger.warning(f"Could not update the Eventbrite churn alert: {e}")


async def handle_mute_clear_panel(query, context, payload):
    """Button in the 👥 Gestisci Iscritti panel: unmutes and redraws the panel."""
    mute = await _unmute(query, payload)
    if not mute:
        return
    event = get_event(mute['event_id'])
    if not event:
        return
    text, keyboard = _render_panel(event['id'], event)
    try:
        await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramError as e:
        if not is_not_modified_error(e):
            logger.warning(f"Could not refresh subscribers panel: {e}")
