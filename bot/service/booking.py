import html
import logging

from core import config
from core.db import get_event, book_seat, unbook_seat, get_user_conflicting_events
from utils.templates import format_event_title_link
from bot.common.messages import send_with_reply_fallback
from bot.service.mentions import describe_telegram_user, format_user_mention, get_user_display_name_and_username
from bot.service.posts import update_event_messages

logger = logging.getLogger(__name__)


def format_conflict_warning_message(user, conflicting_events):
    user_tag = format_user_mention(user)
    count = len(conflicting_events)
    if count == 1:
        header = f"⚠️ <b>Attenzione {user_tag}:</b> risulti già iscritto a un altro evento per la stessa data:\n"
    else:
        header = f"⚠️ <b>Attenzione {user_tag}:</b> risulti già iscritto ad altri {count} eventi per la stessa data:\n"

    items = []
    for ev in conflicting_events:
        sys_val = ev.get('system')
        sys_str = f" (<i>{html.escape(sys_val)}</i>)" if sys_val else ""
        items.append(f"• {format_event_title_link(ev)}{sys_str}")

    footer = (
        "\n\n<i>La tua prenotazione è stata registrata regolarmente. "
        "Se necessario, ricordati di liberare il posto dall'evento a cui non parteciperai!</i>"
    )
    return header + "\n".join(items) + footer


async def send_conflict_warning(context, event, user, conflicting_events, notify_chat, reply_to_message_id=None):
    if not conflicting_events:
        return
    await send_with_reply_fallback(
        context.bot, notify_chat, format_conflict_warning_message(user, conflicting_events),
        reply_to_message_id, log=logger, label="conflict warning",
    )


def _notification_target(query, event):
    """Where booking notices go: the discussion group, replying to the clicked message or the stored booking reply."""
    notify_chat = int(config.DISCUSSION_GROUP_ID) if config.DISCUSSION_GROUP_ID else query.message.chat_id
    if query.message and query.message.chat_id == notify_chat:
        return notify_chat, query.message.message_id
    disc_msg_id = event.get('discussion_message_id')
    return notify_chat, int(disc_msg_id) if disc_msg_id else None


async def _answer_and_log(query, user, action, event_id, success, msg):
    """action is "book" or "unbook"."""
    user_identifier = describe_telegram_user(user)
    if success:
        logger.info(f"{user_identifier} successfully {action}ed a seat for event #{event_id}.")
    else:
        logger.warning(f"{user_identifier} failed to {action} a seat for event #{event_id}: {msg}")
    try:
        await query.answer(msg, show_alert=not success)
    except Exception as e:
        logger.debug(f"Error answering callback query: {e}")


async def _warn_on_same_day_conflicts(context, event_id, event, user, notify_chat, reply_id):
    try:
        conflicting_events = get_user_conflicting_events(
            event_id=event_id,
            user_id=user.id,
            username=user.username or user.first_name,
        )
        await send_conflict_warning(
            context=context,
            event=event,
            user=user,
            conflicting_events=conflicting_events,
            notify_chat=notify_chat,
            reply_to_message_id=reply_id,
        )
    except Exception as e:
        logger.error(f"Error checking or sending conflict warning: {e}")


async def handle_seat_booking(event_id, user, query, context):
    clean_username, clean_fullname = get_user_display_name_and_username(user)
    success, msg = book_seat(event_id, user.id, username=clean_username, full_name=clean_fullname)
    await _answer_and_log(query, user, "book", event_id, success, msg)
    if not success:
        return

    event = get_event(event_id)
    if not event:
        return
    await update_event_messages(context, event_id, event=event, current_query=query)

    notify_chat, reply_id = _notification_target(query, event)
    text = f"✅ {format_user_mention(user)} ha prenotato 1 posto per: {format_event_title_link(event)}"
    await send_with_reply_fallback(context.bot, notify_chat, text, reply_id, log=logger, label="booking notification")
    await _warn_on_same_day_conflicts(context, event_id, event, user, notify_chat, reply_id)


async def handle_seat_unbooking(event_id, user, query, context):
    success, msg = unbook_seat(event_id, user.id, username=getattr(user, 'username', None))
    await _answer_and_log(query, user, "unbook", event_id, success, msg)
    if not success:
        return

    event = get_event(event_id)
    if not event:
        return
    await update_event_messages(context, event_id, event=event, current_query=query)

    notify_chat, reply_id = _notification_target(query, event)
    text = f"❌ {format_user_mention(user)} ha liberato 1 posto per: {format_event_title_link(event)}"
    await send_with_reply_fallback(context.bot, notify_chat, text, reply_id, log=logger, label="unbooking notification")
