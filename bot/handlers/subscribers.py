import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from core.db import get_event, admin_add_subscriber, admin_remove_subscriber, get_reservation_by_user
from bot.common.auth import admin_only, describe_user
from bot.common.parsing import extract_event_id_from_reply
from bot.service.notices import send_admin_action_notice
from bot.service.posts import update_event_messages

logger = logging.getLogger(__name__)

# Must match the ForceReply prompt sent by bot.callbacks.subscribers.handle_add_subscriber_prompt
ADD_SUBSCRIBER_PROMPT_MARKER = "Invia l'username Telegram, rispondendo a questo messaggio, da aggiungere all'evento #"


async def _add_subscriber_and_notify(update, context, event_id, username, seats, source):
    admin_identifier = describe_user(update.effective_user)
    ok, msg = admin_add_subscriber(event_id, username, seats=seats)
    if not ok:
        logger.warning(f"{admin_identifier} failed to add subscriber {username} to event #{event_id} via {source}: {msg}")
        await update.message.reply_text(f"❌ {msg}")
        return

    logger.info(f"{admin_identifier} added subscriber {username} ({seats} seats) to event #{event_id} via {source}.")
    await update_event_messages(context, event_id)
    await send_admin_action_notice(
        context=context,
        event=get_event(event_id),
        target_username=username,
        action="add",
        seats=seats,
        admin_user=update.effective_user,
    )
    await update.message.reply_text(f"✅ {msg}")


@admin_only()
async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.reply_to_message:
        return

    replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
    if ADD_SUBSCRIBER_PROMPT_MARKER not in replied_text:
        return

    m = re.search(r"all'evento #(\d+)", replied_text)
    if not m:
        return

    parts = (update.message.text or "").strip().split()
    if not parts:
        return

    seats = 1
    if len(parts) > 1:
        try:
            seats = int(parts[1])
        except ValueError:
            seats = 1

    await _add_subscriber_and_notify(update, context, int(m.group(1)), parts[0], seats, source="reply")


async def _parse_subscriber_command(update, args, command, default_seats):
    """Returns (event_id, username, seats), or None after replying with usage/validation errors."""
    reply_msg = update.message.reply_to_message
    event_id = extract_event_id_from_reply(reply_msg) if reply_msg else None

    if event_id:
        positional = args
        if not positional:
            await update.message.reply_text(
                f"Uso in risposta a un evento: <code>{command} @username [posti]</code>",
                parse_mode="HTML",
            )
            return None
    else:
        if len(args) < 2:
            await update.message.reply_text(
                f"Uso: <code>{command} &lt;event_id&gt; @username [posti]</code>\n"
                f"Oppure rispondi a un evento con: <code>{command} @username [posti]</code>",
                parse_mode="HTML",
            )
            return None
        try:
            event_id = int(args[0])
        except ValueError:
            await update.message.reply_text("L'ID evento deve essere un numero intero.")
            return None
        positional = args[1:]

    seats = default_seats
    if len(positional) >= 2:
        try:
            seats = int(positional[1])
        except ValueError:
            await update.message.reply_text("I posti devono essere un numero intero.")
            return None
    return event_id, positional[0], seats


@admin_only()
async def event_sub_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed = await _parse_subscriber_command(update, context.args or [], "/event_sub_add", default_seats=1)
    if parsed:
        event_id, username, seats = parsed
        await _add_subscriber_and_notify(update, context, event_id, username, seats, source="/event_sub_add")


@admin_only()
async def event_sub_remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed = await _parse_subscriber_command(update, context.args or [], "/event_sub_remove", default_seats=None)
    if not parsed:
        return
    event_id, username, seats = parsed

    res = get_reservation_by_user(event_id, username=username)
    seats_to_remove = seats
    if res and (seats_to_remove is None or int(seats_to_remove) > res.get('seats_booked', 0)):
        seats_to_remove = res.get('seats_booked', 1)
    if seats_to_remove is None:
        seats_to_remove = 1

    admin_identifier = describe_user(update.effective_user)
    ok, msg = admin_remove_subscriber(event_id, username, seats=seats)
    if not ok:
        logger.warning(f"{admin_identifier} failed to remove subscriber {username} from event #{event_id} via /event_sub_remove: {msg}")
        await update.message.reply_text(f"❌ {msg}")
        return

    logger.info(f"{admin_identifier} removed subscriber {username} ({seats_to_remove} seats) from event #{event_id} via /event_sub_remove.")
    await update_event_messages(context, event_id)
    await send_admin_action_notice(
        context=context,
        event=get_event(event_id),
        target_username=username,
        target_user_id=res.get('user_id') if res else None,
        action="remove",
        seats=seats_to_remove,
        admin_user=update.effective_user,
        target_full_name=res.get('full_name') if res else None,
    )
    await update.message.reply_text(f"✅ {msg}")
