import functools

from core import config
from bot.common.messages import resolve_message

UNAUTHORIZED_REPLY = "Non sei autorizzato."


def describe_user(user, role="Admin"):
    user_id = getattr(user, "id", "unknown")
    username = getattr(user, "username", None)
    return f"{role} {user_id} (@{username})" if username else f"{role} {user_id}"


def is_admin_chat(update) -> bool:
    chat = update.effective_chat
    return bool(chat and config.ADMIN_CHAT_ID and str(chat.id) == str(config.ADMIN_CHAT_ID))


def admin_only(notify=False):
    """Restricts a handler to ADMIN_CHAT_ID; with notify=True, outsiders get an "unauthorized" reply."""
    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(update, context):
            if not is_admin_chat(update):
                if notify:
                    message = resolve_message(update)
                    if message:
                        await message.reply_text(UNAUTHORIZED_REPLY)
                return
            return await handler(update, context)
        return wrapper
    return decorator
