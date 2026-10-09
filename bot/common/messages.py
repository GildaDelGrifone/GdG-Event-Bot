import logging

logger = logging.getLogger(__name__)

CAPTION_LIMIT = 1024


def resolve_message(update):
    return update.message if update.message is not None else (update.effective_message or update.channel_post)


def command_argument(message):
    """Text following the command word, or "" when absent."""
    parts = (message.text or message.caption or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def command_tokens(message):
    return (message.text or message.caption or "").split()[1:]


def truncate_caption(text):
    return text if len(text) <= CAPTION_LIMIT else text[:CAPTION_LIMIT - 4] + "..."


def is_not_modified_error(err):
    return "not modified" in str(err).lower()


async def with_html_fallback(call):
    """Runs call(parse_mode="HTML"), retrying without parse_mode if Telegram rejects the markup."""
    try:
        return await call(parse_mode="HTML")
    except Exception as e:
        logger.warning(f"HTML send failed, retrying as plain text: {e}")
        return await call()


async def send_with_reply_fallback(bot, chat_id, text, reply_to_message_id=None, log=None, label="message"):
    """Sends an HTML message as a reply when possible, falling back to a plain send if the reply target is gone.

    Returns True when a message was delivered.
    """
    log = log or logger
    kwargs = dict(chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    if reply_to_message_id:
        try:
            await bot.send_message(reply_to_message_id=reply_to_message_id, **kwargs)
            return True
        except Exception as e:
            log.warning(f"Failed to send {label} as reply to {reply_to_message_id}: {e}")
    try:
        await bot.send_message(**kwargs)
        return True
    except Exception as e:
        log.error(f"Error sending {label}: {e}")
        return False


async def send_image_or_error(bot, chat_id, image_path, caption, error_text):
    if image_path:
        with open(image_path, 'rb') as f:
            await bot.send_photo(chat_id=chat_id, photo=f, caption=caption)
    else:
        await bot.send_message(chat_id=chat_id, text=error_text)


async def reply_in_chunks(message, parts, limit=4000, prefix="", **reply_kwargs):
    chunk = prefix
    for part in parts:
        if chunk and len(chunk) + len(part) + 1 > limit:
            await message.reply_text(chunk, **reply_kwargs)
            chunk = ""
        chunk += part + "\n"
    if chunk.strip():
        await message.reply_text(chunk, **reply_kwargs)


def private_chat_link(chat_id, message_id, label, fallback_label):
    chat_str = str(chat_id)
    if chat_str.startswith("-100"):
        return f'<a href="https://t.me/c/{chat_str[4:]}/{message_id}">{label}</a>'
    return f"{fallback_label} #{message_id}"
