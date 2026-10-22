import logging

from core import config
from core.db import get_event, book_seat, unbook_seat, get_user_conflicting_events
from utils.templates import (
    EVENTBRITE_TAKEN, format_booking_notice, format_conflict_item, format_conflict_warning, format_event_title_link,
    format_unbooking_notice,
)
from bot.common.messages import send_with_reply_fallback
from bot.service.mentions import describe_telegram_user, format_user_mention, get_user_display_name_and_username
from bot.service.eventbrite import reserve_on_eventbrite
from bot.service.eventbrite_poll import poll_event_now
from bot.service.posts import update_event_messages

logger = logging.getLogger(__name__)


def format_conflict_warning_message(user, conflicting_events):
    items = [format_conflict_item(format_event_title_link(ev), ev.get('system')) for ev in conflicting_events]
    return format_conflict_warning(format_user_mention(user), len(conflicting_events), items)


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
    if success and not await reserve_on_eventbrite(context, event_id):
        # Eventbrite sold the last seat between two polls: undo, then let the poll pull its orders in
        unbook_seat(event_id, user.id, username=clean_username)
        await poll_event_now(context, event_id)
        success, msg = False, EVENTBRITE_TAKEN
    await _answer_and_log(query, user, "book", event_id, success, msg)
    if not success:
        if msg == EVENTBRITE_TAKEN:
            await update_event_messages(context, event_id, current_query=query)
        return

    event = get_event(event_id)
    if not event:
        return
    await update_event_messages(context, event_id, event=event, current_query=query)

    notify_chat, reply_id = _notification_target(query, event)
    text = format_booking_notice(format_user_mention(user), format_event_title_link(event))
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
    text = format_unbooking_notice(format_user_mention(user), format_event_title_link(event))
    await send_with_reply_fallback(context.bot, notify_chat, text, reply_id, log=logger, label="unbooking notification")
