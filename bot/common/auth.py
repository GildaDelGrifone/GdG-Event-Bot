import functools
import logging

from telegram.constants import ChatType
from telegram.ext import ApplicationHandlerStop

from core import config

logger = logging.getLogger(__name__)


def describe_user(user, role="Admin"):
    user_id = getattr(user, "id", "unknown")
    username = getattr(user, "username", None)
    return f"{role} {user_id} (@{username})" if username else f"{role} {user_id}"


def is_admin_chat(update) -> bool:
    chat = update.effective_chat
    return bool(chat and config.ADMIN_CHAT_ID and str(chat.id) == str(config.ADMIN_CHAT_ID))


def is_command_chat(update) -> bool:
    """Commands are answered only in private chats with the bot and in ADMIN_CHAT_ID, never in the channel or a group."""
    chat = update.effective_chat
    return bool(chat) and (getattr(chat, "type", None) == ChatType.PRIVATE or is_admin_chat(update))


async def drop_commands_outside_command_chats(update, context):
    """Registered in an early handler group for every message starting with '/': in a chat where commands are not
    answered it stops the update there, so no command handler can reply in the channel or a public group."""
    if is_command_chat(update):
        return
    chat = update.effective_chat
    logger.debug(f"Command ignored in chat {getattr(chat, 'id', '?')} ({getattr(chat, 'type', '?')}).")
    raise ApplicationHandlerStop


def admin_only():
    """Restricts a handler to ADMIN_CHAT_ID; outsiders get no reply (no noise in public chats)."""
    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(update, context):
            if not is_admin_chat(update):
                return
            return await handler(update, context)
        return wrapper
    return decorator
