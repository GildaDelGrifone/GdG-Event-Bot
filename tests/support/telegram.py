"""Factories for the python-telegram-bot objects handlers receive, pre-wired with AsyncMocks."""
from unittest.mock import AsyncMock, MagicMock

ADMIN_CHAT_ID = "999"
ADMIN_USER_ID = 998877
ADMIN_USERNAME = "testadmin"

_BOT_COROUTINES = (
    "send_message", "send_photo", "copy_message", "edit_message_text", "edit_message_caption",
    "edit_message_media", "edit_message_reply_markup", "delete_message", "set_my_commands", "get_me",
)


def make_bot(username=None):
    bot = MagicMock()
    for name in _BOT_COROUTINES:
        setattr(bot, name, AsyncMock())
    bot.username = username
    return bot


def make_context(args=None, bot_username=None):
    context = MagicMock()
    context.args = list(args) if args is not None else []
    context.bot = make_bot(bot_username)
    return context


def make_user(user_id=ADMIN_USER_ID, username=ADMIN_USERNAME, first_name="Admin", full_name=None):
    user = MagicMock()
    user.id = user_id
    user.username = username
    user.first_name = first_name
    user.last_name = None
    user.full_name = full_name if full_name is not None else first_name
    return user


def make_message(text=None, caption=None, chat_id=ADMIN_CHAT_ID, message_id=1, reply_to=None, photo=None,
                 document=None, media_group_id=None):
    """A Message whose optional media fields are explicitly None (MagicMock would invent them)."""
    message = MagicMock()
    message.text = text
    message.caption = caption
    message.chat_id = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
    message.message_id = message_id
    message.reply_to_message = reply_to
    message.photo = photo
    message.document = document
    message.media_group_id = media_group_id
    for name in ("reply_text", "reply_photo", "delete", "edit_text", "edit_caption", "edit_media"):
        setattr(message, name, AsyncMock())
    return message


def channel_message(chat_id, message_id, text=None, caption=None, media_group_id=None, photo=None):
    """A post published in a channel by a human, not a bot-published event post (no inline keyboard)."""
    message = make_message(text=text, caption=caption, chat_id=chat_id, message_id=message_id,
                           media_group_id=media_group_id, photo=photo)
    message.from_user.is_bot = False
    message.reply_markup = None
    return message


def make_update(message=None, chat_id=ADMIN_CHAT_ID, user=None, chat_type="group", **message_kwargs):
    """Update for a command/message; extra kwargs build the message (text=, reply_to=, photo=, ...)."""
    update = MagicMock()
    update.message = message if message is not None else make_message(chat_id=chat_id, **message_kwargs)
    update.effective_message = update.message
    update.channel_post = None
    update.effective_chat.id = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
    update.effective_chat.type = chat_type
    update.effective_user = user if user is not None else make_user()
    return update


def admin_update(text=None, reply_to=None, **kwargs):
    """Update sent in ADMIN_CHAT_ID by the default admin user (patch core.config.ADMIN_CHAT_ID to ADMIN_CHAT_ID)."""
    return make_update(text=text, reply_to=reply_to, chat_id=ADMIN_CHAT_ID, **kwargs)


def admin_card(event_id, text="Event caption", caption=None, photo=None, button_prefix="publish_event_", message_id=500):
    """The bot's event card in the admin chat (what admins reply to), identified by its inline button."""
    card = make_message(text=text, caption=caption, photo=photo, message_id=message_id)
    card.reply_markup.inline_keyboard = [[MagicMock(callback_data=f"{button_prefix}{event_id}")]]
    return card


def callback_update(data, chat_id=ADMIN_CHAT_ID, message_id=123, text="Post text", caption=None, photo=None, user=None):
    """Returns (update, query) for an inline-button press."""
    query = MagicMock()
    query.data = data
    query.from_user = user if user is not None else make_user()
    query.message = make_message(text=text, caption=caption, chat_id=chat_id, message_id=message_id, photo=photo)
    for name in ("answer", "edit_message_text", "edit_message_caption", "edit_message_reply_markup"):
        setattr(query, name, AsyncMock())
    update = MagicMock()
    update.callback_query = query
    update.effective_user = query.from_user
    return update, query


def telegram_photo(image_bytes):
    """A PhotoSize/Document stand-in whose get_file().download_as_bytearray() yields image_bytes."""
    photo = MagicMock()
    tg_file = MagicMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(image_bytes))
    photo.get_file = AsyncMock(return_value=tg_file)
    return photo
