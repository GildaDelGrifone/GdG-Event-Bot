import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.event_generator.command import event_generate_command
from tests.support.config import patched_config
from tests.support.telegram import make_context, make_message, make_update

ADMIN_CHAT = "12345"


class TestEventGenerateCommand(unittest.IsolatedAsyncioTestCase):
    async def test_event_generate_command_unauthorized(self):
        update = make_update(chat_id=99999)

        with patched_config(ADMIN_CHAT_ID=ADMIN_CHAT):
            await event_generate_command(update, make_context())
            update.message.reply_text.assert_called_once_with("Non sei autorizzato.")

    async def test_event_generate_command_no_text_shows_help(self):
        update = make_update(chat_id=ADMIN_CHAT, text="/event_generate")

        with patched_config(ADMIN_CHAT_ID=ADMIN_CHAT):
            await event_generate_command(update, make_context())
            update.message.reply_text.assert_called_once()
            self.assertIn("Uso del comando /event_generate", update.message.reply_text.call_args[0][0])

    async def test_event_generate_command_success(self):
        update = make_update(chat_id=ADMIN_CHAT, text="/event_generate Catan, venerdì 10 ottobre, host Destard")
        status_msg = make_message()
        update.message.reply_text.return_value = status_msg

        with patched_config(ADMIN_CHAT_ID=ADMIN_CHAT), \
             patch("bot.event_generator.command.process_event_generation", AsyncMock(return_value=(True, "Successo"))):
            await event_generate_command(update, make_context())
            status_msg.edit_text.assert_called_once_with("✅ Successo")

    async def test_event_generate_command_none_message_handled_gracefully(self):
        # Hand-built: an update with no message of any kind
        update = MagicMock()
        update.message = None
        update.effective_message = None
        update.channel_post = None

        # Should return cleanly without raising AttributeError: 'NoneType' object has no attribute 'text'
        await event_generate_command(update, make_context())

    async def test_event_generate_command_channel_post_fallback(self):
        channel_post = make_message(text="/event_generate Root, domani 21:00, host Marco", chat_id=ADMIN_CHAT)
        status_msg = make_message()
        channel_post.reply_text.return_value = status_msg
        update = make_update(message=channel_post, chat_id=ADMIN_CHAT)
        update.message = None
        update.channel_post = channel_post

        with patched_config(ADMIN_CHAT_ID=ADMIN_CHAT), \
             patch("bot.event_generator.command.process_event_generation", AsyncMock(return_value=(True, "Successo"))):
            await event_generate_command(update, make_context())
            status_msg.edit_text.assert_called_once_with("✅ Successo")


if __name__ == "__main__":
    unittest.main()
