import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import core.db as db
from bot.callbacks.router import handle_callback_query
from bot.handlers.subscribers import handle_admin_reply
from bot.state import runtime_state
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import admin_update, callback_update, make_context, make_message


def _buttons(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]


class TestEditMenu(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.event_id = create_event(title="Vecchio", date="10-12-2026 21:00", normalized_date="10-12-2026")
        self.context = make_context()
        self.context.bot.send_message.return_value = MagicMock(message_id=900)
        runtime_state.edit_prompts.clear()
        self.addCleanup(runtime_state.edit_prompts.clear)

    async def press(self, data):
        update, query = callback_update(data, text="Card", message_id=500)
        with as_admin_chat(), patch("bot.service.edits.update_event_messages", AsyncMock()):
            await handle_callback_query(update, self.context)
        return query

    async def answer_prompt(self, text, prompt_text=None):
        prompt = make_message(text=prompt_text or f"✏️ Modifica evento #{self.event_id} — Titolo", message_id=900)
        update = admin_update(text=text, reply_to=prompt)
        with as_admin_chat(), patch("bot.service.edits.update_event_messages", AsyncMock()) as update_messages:
            await handle_admin_reply(update, self.context)
        return update, update_messages

    async def test_menu_and_back(self):
        query = await self.press(f"editmenu_{self.event_id}")
        menu = query.edit_message_reply_markup.call_args.kwargs["reply_markup"]
        self.assertIn(f"editfield_{self.event_id}_title", _buttons(menu))
        self.assertIn(f"edittype_{self.event_id}", _buttons(menu))
        query = await self.press(f"editback_{self.event_id}")
        card = query.edit_message_reply_markup.call_args.kwargs["reply_markup"]
        self.assertEqual(_buttons(card)[0], f"publish_event_{self.event_id}")

    async def test_field_prompt_then_answer_edits_the_event_and_the_card(self):
        query = await self.press(f"editfield_{self.event_id}_title")
        prompt = self.context.bot.send_message.call_args.kwargs
        self.assertIn("Vecchio", prompt["text"])
        self.assertEqual(prompt["reply_to_message_id"], 500)
        self.assertIn(900, runtime_state.edit_prompts)

        update, _ = await self.answer_prompt("Nuovo Titolo")
        self.assertEqual(db.get_event(self.event_id)["title"], "Nuovo Titolo")
        self.assertIn("aggiornato", update.message.reply_text.call_args.args[0])
        card_edit = query.message.edit_text.call_args.kwargs
        self.assertIn("Nuovo Titolo", card_edit["text"])
        self.assertEqual(_buttons(card_edit["reply_markup"])[0], f"publish_event_{self.event_id}")
        self.assertNotIn(900, runtime_state.edit_prompts)

    async def test_a_bad_value_gets_the_command_error_and_the_prompt_stays_open(self):
        await self.press(f"editfield_{self.event_id}_date")
        update, _ = await self.answer_prompt("domani forse")
        self.assertIn("Formato data non valido", update.message.reply_text.call_args.args[0])
        self.assertEqual(db.get_event(self.event_id)["normalized_date"], "10-12-2026")
        self.assertIn(900, runtime_state.edit_prompts)

    async def test_an_answer_after_a_restart_asks_to_reopen_the_menu(self):
        update, _ = await self.answer_prompt("Nuovo Titolo")
        self.assertIn("non è più valida", update.message.reply_text.call_args.args[0])
        self.assertEqual(db.get_event(self.event_id)["title"], "Vecchio")

    async def test_type_toggle_flips_and_keeps_the_menu(self):
        before = db.get_event(self.event_id)["is_roleplay"]
        query = await self.press(f"edittype_{self.event_id}")
        self.assertEqual(db.get_event(self.event_id)["is_roleplay"], 0 if before else 1)
        self.assertIn("aggiornato", query.answer.call_args.args[0])
        menu = query.message.edit_text.call_args.kwargs["reply_markup"]
        self.assertIn(f"edittype_{self.event_id}", _buttons(menu))


if __name__ == "__main__":
    unittest.main()
