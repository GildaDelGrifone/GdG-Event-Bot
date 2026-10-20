import unittest
from unittest.mock import AsyncMock

from bot.callbacks.router import handle_callback_query
from bot.keyboards import get_venue_keyboard
from tests.support.telegram import callback_update, make_context


class TestVenueClose(unittest.IsolatedAsyncioTestCase):
    def test_keyboard_ends_with_close_button(self):
        keyboard = get_venue_keyboard([("1", "Sede A"), ("2", "Sede B")], "1", "1")
        last = keyboard.inline_keyboard[-1][0]
        self.assertEqual((last.text, last.callback_data), ("❌ Chiudi", "ebvenue_close"))
        self.assertEqual(len(keyboard.inline_keyboard), 3)

    async def test_close_deletes_the_message(self):
        update, query = callback_update("ebvenue_close")
        query.message.delete = AsyncMock()

        await handle_callback_query(update, make_context())

        query.message.delete.assert_awaited_once()
        query.answer.assert_awaited_once_with("Chiuso.")


if __name__ == "__main__":
    unittest.main()
