import os
import unittest
from unittest.mock import AsyncMock, patch

from bot.handlers.story import event_regenerate_story_command
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import admin_card, admin_update, make_context, make_message, make_update


class TestEventRegenerateStoryCommand(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.event_id = create_event(
            status="approved", title="Terraforming Mars", date="Venerdì 20-10-2026", normalized_date="20-10-2026",
            system="Sci-Fi", host="Elon", seats="2/4", booked_seats=2, max_seats=4,
            description="Colonizziamo Marte", extra_info="", is_roleplay=0,
        )
        self.context = make_context()

    def _story_file(self, name, data):
        path = os.path.join(self.temp_dir.name, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def _with_status_message(self, update):
        status_msg = make_message()
        update.message.reply_text.return_value = status_msg
        return status_msg

    async def test_unauthorized_user_ignored(self):
        update = make_update(chat_id=11111)

        with as_admin_chat():
            await event_regenerate_story_command(update, self.context)

        update.message.reply_text.assert_not_called()

    async def test_no_reply_and_no_arg_shows_help(self):
        # The old version of this test was truncated before running the command; completed with the help check
        update = admin_update("/event_regenerate_story")

        with as_admin_chat():
            await event_regenerate_story_command(update, self.context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Rispondi al messaggio di un evento", update.message.reply_text.call_args[0][0])

    async def test_reply_to_non_event_message_shows_error(self):
        reply_msg = make_message(text="Just a casual message without event ID", message_id=12345)
        reply_msg.reply_markup = None
        update = admin_update("/event_regenerate_story", reply_to=reply_msg)

        with as_admin_chat():
            await event_regenerate_story_command(update, self.context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Rispondi al messaggio di un evento", update.message.reply_text.call_args[0][0])

    async def test_event_not_found_in_db(self):
        update = admin_update("/event_regenerate_story 99999")

        with as_admin_chat():
            await event_regenerate_story_command(update, self.context)

        update.message.reply_text.assert_called_once()
        self.assertIn("Evento #99999 non trovato", update.message.reply_text.call_args[0][0])

    async def test_success_via_reply_to_event(self):
        update = admin_update("/event_regenerate_story", reply_to=admin_card(self.event_id))
        status_msg = self._with_status_message(update)
        fake_story_path = self._story_file("fake_story.jpg", b"fake story image data")

        with as_admin_chat(), \
             patch("bot.handlers.story.create_story_image", return_value=fake_story_path) as mock_create, \
             patch("bot.handlers.story.send_image_or_error", new_callable=AsyncMock) as mock_send:
            await event_regenerate_story_command(update, self.context)

        mock_create.assert_called_once()
        mock_send.assert_called_once()
        send_args = mock_send.call_args
        self.assertEqual(send_args[0][1], 999)
        self.assertEqual(send_args[0][2], fake_story_path)
        self.assertIn(f"#{self.event_id}", send_args[1]["caption"])
        status_msg.delete.assert_called_once()

    async def test_success_via_id_argument(self):
        update = admin_update(f"/event_regenerate_story {self.event_id}")
        status_msg = self._with_status_message(update)
        fake_story_path = self._story_file("fake_story2.jpg", b"fake story image data 2")

        with as_admin_chat(), \
             patch("bot.handlers.story.create_story_image", return_value=fake_story_path) as mock_create, \
             patch("bot.handlers.story.send_image_or_error", new_callable=AsyncMock) as mock_send:
            await event_regenerate_story_command(update, self.context)

        mock_create.assert_called_once()
        mock_send.assert_called_once()
        status_msg.delete.assert_called_once()

    async def test_story_generation_error(self):
        update = admin_update(f"/event_regenerate_story {self.event_id}")
        status_msg = self._with_status_message(update)

        with as_admin_chat(), patch("bot.handlers.story.create_story_image", return_value=None) as mock_create:
            await event_regenerate_story_command(update, self.context)

        mock_create.assert_called_once()
        status_msg.edit_text.assert_called_once()
        self.assertIn("Errore durante la generazione", status_msg.edit_text.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
