import unittest

import core.db as db
from bot.handlers.event_status import event_cancel_command, event_cancel_eventbrite_command, event_delete_command
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import admin_card, admin_update, make_context, make_update


class EventStatusCommandCase(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.context = make_context()

    async def run_command(self, command, update):
        with as_admin_chat():
            await command(update, self.context)

    def replies(self, update):
        return update.message.reply_text.call_args_list

    def keyboard(self, update):
        markup = self.replies(update)[0].kwargs["reply_markup"]
        return [b.callback_data for row in markup.inline_keyboard for b in row]


class TestEventCancelCommand(EventStatusCommandCase):
    async def test_prompt_carries_the_command_confirmation(self):
        event_id = create_event(status="approved", title="Avventura")
        update = admin_update(f"/event_cancel {event_id}")
        await self.run_command(event_cancel_command, update)
        self.assertIn(f"#{event_id} «Avventura»", self.replies(update)[0].args[0])
        self.assertEqual(self.keyboard(update), [f"cancel_confirm_{event_id}_cmd", f"cancel_abort_{event_id}_cmd"])
        self.assertEqual(db.get_event(event_id)["status"], "approved")  # nothing happens before the confirmation

    async def test_event_id_from_the_replied_card(self):
        event_id = create_event(status="approved")
        update = admin_update("/event_cancel", reply_to=admin_card(event_id, button_prefix="cancel_event_"))
        await self.run_command(event_cancel_command, update)
        self.assertEqual(self.keyboard(update)[0], f"cancel_confirm_{event_id}_cmd")

    async def test_usage_and_unknown_event(self):
        update = admin_update("/event_cancel")
        await self.run_command(event_cancel_command, update)
        self.assertIn("/event_cancel <id>", self.replies(update)[0].args[0])

        update = admin_update("/event_cancel 999")
        await self.run_command(event_cancel_command, update)
        self.assertEqual(self.replies(update)[0].args[0], "❌ Evento #999 non trovato")

    async def test_only_published_events(self):
        cancelled = create_event(status="cancelled")
        pending = create_event()
        update = admin_update(f"/event_cancel {cancelled}")
        await self.run_command(event_cancel_command, update)
        self.assertEqual(self.replies(update)[0].args[0], "Evento già annullato.")
        update = admin_update(f"/event_cancel {pending}")
        await self.run_command(event_cancel_command, update)
        self.assertIn("solo gli eventi pubblicati", self.replies(update)[0].args[0])
        self.assertNotIn("reply_markup", self.replies(update)[0].kwargs)

    async def test_outside_the_admin_chat_is_ignored(self):
        event_id = create_event(status="approved")
        update = make_update(text=f"/event_cancel {event_id}", chat_id="-100999")
        await self.run_command(event_cancel_command, update)
        update.message.reply_text.assert_not_called()


class TestEventCancelEventbriteCommand(EventStatusCommandCase):
    async def test_prompt_for_a_linked_live_event(self):
        event_id = create_event(status="approved")
        db.set_eventbrite_info(event_id, eventbrite_event_id="eb1", eventbrite_status="live")
        update = admin_update(f"/event_cancel_eventbrite {event_id}")
        await self.run_command(event_cancel_eventbrite_command, update)
        self.assertIn("solo su Eventbrite", self.replies(update)[0].args[0])
        self.assertEqual(self.keyboard(update), [f"eb_cancel_do_{event_id}_cmd", f"cancel_abort_{event_id}_cmd"])

    async def test_nothing_to_cancel(self):
        event_id = create_event(status="approved")
        update = admin_update(f"/event_cancel_eventbrite {event_id}")
        await self.run_command(event_cancel_eventbrite_command, update)
        self.assertEqual(self.replies(update)[0].args[0], "Niente da annullare su Eventbrite per questo evento.")


class TestEventDeleteCommand(EventStatusCommandCase):
    async def test_prompt_for_a_cancelled_event(self):
        event_id = create_event(status="cancelled")
        update = admin_update(f"/event_delete {event_id}")
        await self.run_command(event_delete_command, update)
        self.assertIn("Eliminare per sempre", self.replies(update)[0].args[0])
        self.assertEqual(self.keyboard(update), [f"delete_confirm_{event_id}_cmd", f"delete_abort_{event_id}_cmd"])
        self.assertIsNotNone(db.get_event(event_id))

    async def test_only_cancelled_events(self):
        event_id = create_event(status="approved")
        update = admin_update(f"/event_delete {event_id}")
        await self.run_command(event_delete_command, update)
        self.assertIn("solo gli eventi annullati", self.replies(update)[0].args[0])

    async def test_eventbrite_orders_still_open(self):
        event_id = create_event(status="cancelled")
        db.set_eventbrite_info(event_id, eventbrite_event_id="eb1", eventbrite_status="closed")
        update = admin_update(f"/event_delete {event_id}")
        await self.run_command(event_delete_command, update)
        self.assertIn("prenotazioni attive su Eventbrite", self.replies(update)[0].args[0])

    async def test_usage(self):
        update = admin_update("/event_delete")
        await self.run_command(event_delete_command, update)
        self.assertIn("/event_delete <id>", self.replies(update)[0].args[0])


if __name__ == "__main__":
    unittest.main()
