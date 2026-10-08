import logging

from telegram import Update
from telegram.ext import ContextTypes

from core import config
from core.db import get_event_by_telegram_message_id, update_discussion_message_info
from core.scheduler.recap import generate_daily_recap
from utils.date_utils import parse_user_date
from utils.templates import recap_links_text
from bot.common.auth import admin_only, describe_user
from bot.common.messages import is_not_modified_error
from bot.keyboards import get_event_booking_keyboard
from bot.state import runtime_state

logger = logging.getLogger(__name__)


@admin_only()
async def manual_recap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    logger.info(f"{describe_user(update.effective_user)} triggered manual recap (args={args}).")
    date_str = None
    if args:
        parsed = parse_user_date(args[0])
        if not parsed:
            if update.message:
                await update.message.reply_text(
                    "❌ Formato data non valido.\n"
                    "Usa il formato DD-MM-YYYY (es. /recap_generate 05-09-2026)."
                )
            return
        date_str = parsed[0].strftime("%d-%m-%Y")

    reply_id = update.message.message_id if update.message else None
    success = await generate_daily_recap(context.bot, date_str, is_manual=True, reply_to_message_id=reply_id)
    if success:
        done_text = f"Recap generato per la data: {date_str or 'Oggi'}"
        if update.message:
            await update.message.reply_text(done_text)
        else:
            await context.bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=done_text)


def _channel_forward_origin(message):
    forward_origin = getattr(message, 'forward_origin', None)
    if forward_origin and getattr(forward_origin, 'type', None) == 'channel':
        return forward_origin
    return None


async def _reply_recap_links(context, message, forward_msg_id):
    links_text = recap_links_text(runtime_state.last_recap_events)
    if not links_text:
        return
    try:
        await context.bot.send_message(
            chat_id=message.chat_id,
            text=links_text,
            reply_to_message_id=message.message_id,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Successfully posted recap links reply in discussion group for recap message {forward_msg_id}")
    except Exception as e:
        logger.error(f"Error posting recap links to discussion group: {e}")


async def handle_discussion_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Attaches booking buttons (or recap links) under channel posts auto-forwarded into the discussion group."""
    message = update.message or update.channel_post
    if not message:
        return

    channel_origin = _channel_forward_origin(message)
    # Plain user chatter in the discussion group is neither an automatic nor a channel forward
    if not getattr(message, 'is_automatic_forward', False) and not channel_origin:
        return

    if channel_origin:
        forward_msg_id = getattr(channel_origin, 'message_id', None)
    else:
        forward_msg_id = getattr(message, 'forward_from_message_id', None)

    logger.info(f"Detected channel forward in discussion group: msg_id={message.message_id}, origin_msg_id={forward_msg_id}")

    if not forward_msg_id:
        return

    if forward_msg_id == runtime_state.last_recap_message_id:
        await _reply_recap_links(context, message, forward_msg_id)
        return

    event = get_event_by_telegram_message_id(forward_msg_id)
    if not event:
        logger.warning(f"No event found in DB for forwarded message_id={forward_msg_id}")
        return

    pub_keyboard = get_event_booking_keyboard(event['id'], event=event, bot_username=getattr(context.bot, "username", None))

    if event.get('discussion_message_id'):
        logger.info(f"Event {event['id']} already has discussion_message_id={event['discussion_message_id']}")
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=message.chat_id,
                message_id=event['discussion_message_id'],
                reply_markup=pub_keyboard
            )
        except Exception as e:
            if not is_not_modified_error(e):
                logger.error(f"Error updating existing discussion reply markup: {e}")
        return

    try:
        reply_msg = await context.bot.send_message(
            chat_id=message.chat_id,
            text="👇 Gestisci qui la tua prenotazione!",
            reply_to_message_id=message.message_id,
            reply_markup=pub_keyboard
        )
        update_discussion_message_info(event['id'], reply_msg.message_id, message.chat_id)
        logger.info(f"Successfully posted booking buttons reply in discussion group for event {event['id']}")
    except Exception as e:
        logger.error(f"Error sending booking buttons to discussion group: {e}")
