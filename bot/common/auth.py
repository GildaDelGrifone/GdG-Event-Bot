import functools

from core import config


def describe_user(user, role="Admin"):
    user_id = getattr(user, "id", "unknown")
    username = getattr(user, "username", None)
    return f"{role} {user_id} (@{username})" if username else f"{role} {user_id}"


def is_admin_chat(update) -> bool:
    chat = update.effective_chat
    return bool(chat and config.ADMIN_CHAT_ID and str(chat.id) == str(config.ADMIN_CHAT_ID))


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
