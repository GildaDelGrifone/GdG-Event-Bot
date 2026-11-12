import os
import unittest
from unittest.mock import patch

from telegram.error import BadRequest, Forbidden

import core.db as db
from core.eventbrite import EventbriteError
from bot.service.deletion import delete_event_everywhere
from tests.support.config import eventbrite_credentials, patched_config
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import make_context

CHANNEL = "-1001"
GROUP = "-1002"


class TestDeleteEventEverywhere(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.day = os.path.join(self.temp_dir.name, "2026", "10", "28")
        os.makedirs(self.day)
        self.image = os.path.join(self.day, "event_a.jpg")
        with open(self.image, "wb") as f:
            f.write(b"img")
        self.event_id = create_event(
            status="cancelled", image_path=self.image, telegram_message_id=11,
            message_link="https://t.me/c/1/11", normalized_date="28-10-2026",
        )
        db.update_discussion_message_info(self.event_id, 22, GROUP)
        db.book_seat(self.event_id, 1, "mario")
        self.context = make_context()
        config = patched_config(PUBLIC_CHANNEL_ID=CHANNEL, DISCUSSION_GROUP_ID=GROUP, DATA_DIR=self.temp_dir.name)
        config.__enter__()
        self.addCleanup(config.__exit__, None, None, None)

    def deleted_messages(self):
        return [(c.kwargs["chat_id"], c.kwargs["message_id"]) for c in self.context.bot.delete_message.call_args_list]

    async def test_everything_is_removed(self):
        result = await delete_event_everywhere(self.context, db.get_event(self.event_id))

        self.assertTrue(result.deleted)
        self.assertEqual(result.leftovers, [])
        self.assertEqual(self.deleted_messages(), [(CHANNEL, 11), (int(GROUP), 22)])
        self.assertIsNone(db.get_event(self.event_id))
        self.assertEqual(db.get_reservations_for_event(self.event_id), [])
        self.assertFalse(os.path.exists(self.image))

    async def test_messages_already_gone_count_as_deleted(self):
        self.context.bot.delete_message.side_effect = BadRequest("Message to delete not found")
        result = await delete_event_everywhere(self.context, db.get_event(self.event_id))
        self.assertEqual(result.leftovers, [])
        self.assertIsNone(db.get_event(self.event_id))

    async def test_undeletable_messages_are_reported_and_the_event_still_goes(self):
        self.context.bot.delete_message.side_effect = Forbidden("not enough rights")
        result = await delete_event_everywhere(self.context, db.get_event(self.event_id))
        self.assertEqual([desc for desc, _link in result.leftovers],
                         ["post sul canale", "messaggio di prenotazione nel gruppo di discussione"])
        self.assertEqual(result.leftovers[0][1], "https://t.me/c/1/11")
        self.assertIsNone(db.get_event(self.event_id))

    async def test_shared_image_is_kept(self):
        create_event(image_path=self.image)
        await delete_event_everywhere(self.context, db.get_event(self.event_id))
        self.assertTrue(os.path.exists(self.image))

    async def test_eventbrite_refusal_touches_nothing(self):
        db.set_eventbrite_info(self.event_id, eventbrite_event_id="eb1", eventbrite_status="canceled")
        error = EventbriteError(400, "CANNOT_DELETE", "Event has orders")
        with eventbrite_credentials(), \
             patch("bot.service.deletion.delete_eventbrite_event", side_effect=error) as eb_delete:
            result = await delete_event_everywhere(self.context, db.get_event(self.event_id))

        eb_delete.assert_called_once_with("eb1")
        self.assertFalse(result.deleted)
        self.assertIn("Event has orders", result.eventbrite_error)
        self.context.bot.delete_message.assert_not_awaited()
        self.assertIsNotNone(db.get_event(self.event_id))
        self.assertTrue(os.path.exists(self.image))

    async def test_eventbrite_event_already_deleted_by_hand(self):
        db.set_eventbrite_info(self.event_id, eventbrite_event_id="eb1", eventbrite_status="canceled")
        with eventbrite_credentials(), \
             patch("bot.service.deletion.delete_eventbrite_event", side_effect=EventbriteError(404, "NOT_FOUND")):
            result = await delete_event_everywhere(self.context, db.get_event(self.event_id))
        self.assertTrue(result.deleted)
        self.assertIsNone(db.get_event(self.event_id))

    async def test_linked_event_with_eventbrite_unconfigured_is_kept(self):
        db.set_eventbrite_info(self.event_id, eventbrite_event_id="eb1", eventbrite_status="canceled")
        with patched_config(EVENTBRITE_TOKEN=None):
            result = await delete_event_everywhere(self.context, db.get_event(self.event_id))
        self.assertFalse(result.deleted)
        self.assertIsNotNone(db.get_event(self.event_id))


if __name__ == "__main__":
    unittest.main()
