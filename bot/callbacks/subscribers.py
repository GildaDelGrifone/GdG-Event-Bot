import logging

from telegram import ForceReply

from core.db import get_event, get_reservations_for_event, get_reservation, admin_add_seat, admin_remove_seat
from utils.templates import format_event_title_link, format_reservation_subscriber_display
from bot.common.auth import describe_user
from bot.keyboards import get_subscribers_management_keyboard
from bot.service.notices import send_admin_action_notice
from bot.service.posts import update_event_messages

logger = logging.getLogger(__name__)

PANEL_TITLE = "Gestione Iscritti"


def format_subscribers_management_view(event, reservations):
    booked = int(event.get('booked_seats', 0) or 0)
    max_s = event.get('max_seats')
    max_str = str(max_s) if max_s is not None else "Nessun limite"

    text = (
        f"👥 <b>{PANEL_TITLE}</b>\n"
        f"📌 {format_event_title_link(event)}\n"
        f"🪑 Posti occupati: <b>{booked}/{max_str}</b>\n\n"
    )

    if not reservations:
        text += "<i>Nessun utente iscritto al momento.</i>\n"
    else:
        text += "<b>Iscritti:</b>\n"
        for i, res in enumerate(reservations, 1):
            seats = res.get('seats_booked', 1)
            posti_str = "posto" if seats == 1 else "posti"
            text += f"{i}. <b>{format_reservation_subscriber_display(res, as_html=True)}</b> — {seats} {posti_str}\n"

    text += (
        f"\n<i>Modifica con i tasti sotto oppure invia:</i>\n"
        f"<code>/event_sub_add {event['id']} @username [posti]</code>\n"
        f"<code>/event_sub_remove {event['id']} @username [posti]</code>"
    )
    return text


def _render_panel(event_id, event):
    reservations = get_reservations_for_event(event_id)
    return format_subscribers_management_view(event, reservations), get_subscribers_management_keyboard(event_id, reservations)


async def handle_manage_subs(query, context, payload):
    await query.answer()
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} opened subscribers management panel for event #{event_id}.")
    event = get_event(event_id)
    if not event:
        await query.answer("Evento non trovato.", show_alert=True)
        return

    text, keyboard = _render_panel(event_id, event)

    # "🔄 Aggiorna" inside the panel refreshes it; the button on the event card opens a new panel
    if query.message and query.message.text and PANEL_TITLE in query.message.text:
        try:
            await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.debug(f"Edit message unchanged on refresh: {e}")
    else:
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=text,
            reply_markup=keyboard,
            reply_to_message_id=query.message.message_id,
            parse_mode="HTML",
        )


async def _adjust_seat(query, context, payload, action):
    """action is "add" (➕) or "remove" (➖) for one seat of an existing reservation."""
    event_id, res_id = (int(part) for part in payload.split("_")[:2])
    res = get_reservation(res_id)
    admin_identifier = describe_user(query.from_user)
    verb = "increment" if action == "add" else "decrement"

    ok, msg = (admin_add_seat if action == "add" else admin_remove_seat)(event_id, res_id)
    if not ok:
        logger.warning(f"{admin_identifier} failed to {verb} seat for reservation #{res_id} in event #{event_id}: {msg}")
        await query.answer(msg, show_alert=True)
        return

    target_desc = f"user {res.get('username') or res.get('user_id')}" if res else f"reservation #{res_id}"
    logger.info(f"{admin_identifier} {verb}ed seat for {target_desc} in event #{event_id}.")
    await query.answer(msg)
    await update_event_messages(context, event_id)

    event = get_event(event_id)
    if res:
        await send_admin_action_notice(
            context=context,
            event=event,
            target_username=res.get('username'),
            target_full_name=res.get('full_name'),
            target_user_id=res.get('user_id'),
            action=action,
            seats=1,
            admin_user=query.from_user,
        )

    text, keyboard = _render_panel(event_id, event)
    try:
        await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass


async def handle_seat_increment(query, context, payload):
    await _adjust_seat(query, context, payload, "add")


async def handle_seat_decrement(query, context, payload):
    await _adjust_seat(query, context, payload, "remove")


async def handle_add_subscriber_prompt(query, context, payload):
    await query.answer()
    event_id = int(payload)
    logger.info(f"{describe_user(query.from_user)} opened add-subscriber prompt for event #{event_id}.")
    # bot.handlers.subscribers.handle_admin_reply matches replies on this exact wording
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"✏️ Invia l'username Telegram, rispondendo a questo messaggio, da aggiungere all'evento #{event_id} (es. <code>@mario</code> oppure <code>@mario 2</code>):\nOppure usa: <code>/event_sub_add {event_id} @username [posti]</code>",
        reply_markup=ForceReply(selective=True),
        parse_mode="HTML",
    )


async def handle_close_panel(query, context, payload):
    await query.answer("Chiuso.")
    logger.info(f"{describe_user(query.from_user)} closed subscribers management panel.")
    try:
        await query.message.delete()
    except Exception:
        pass
