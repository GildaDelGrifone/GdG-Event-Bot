import unittest
from unittest.mock import patch

import core.db as db
from bot.callbacks.venues import handle_venue_pick
from bot.handlers.control import (
    bot_eventbrite_only_toggle_command, bot_eventbrite_venue_command, bot_pause_command, bot_resume_command, bot_status_command,
)
from bot.state import runtime_state
from bot.handlers.edit import event_edit_command
from tests.support.config import as_admin_chat, eventbrite_credentials, patched_config
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import admin_update, callback_update, make_context, make_message, make_user


def _info_messages(mock_logger):
    return [c[0][0] for c in mock_logger.info.call_args_list]


class TestAdminCommandAuditLogging(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_admin_commands_logging(self):
        update = admin_update(user=make_user(998877, "admin_boss"))
        context = make_context()

        with as_admin_chat(), patch("bot.handlers.control.logger") as mock_logger:
            await bot_pause_command(update, context)
            self.assertTrue(any("998877" in msg and "paused" in msg for msg in _info_messages(mock_logger)))

            await bot_resume_command(update, context)
            self.assertTrue(any("998877" in msg and "resumed" in msg for msg in _info_messages(mock_logger)))

        ev_id = create_event(title="Log Test Event")
        reply_msg = make_message(text=f"Evento #{ev_id}")
        reply_msg.reply_markup = None
        update.message.reply_to_message = reply_msg
        update.message.text = "/event_edit_title New Glorious Title"

        with as_admin_chat(), patch("bot.handlers.edit.logger") as mock_logger:
            await event_edit_command(update, context)
            self.assertTrue(any("998877" in msg and "title" in msg and f"#{ev_id}" in msg for msg in _info_messages(mock_logger)))
            self.assertEqual(db.get_event(ev_id)["title"], "New Glorious Title")


class TestEventbriteOnlyToggle(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = patch.object(runtime_state, "eventbrite_only", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_toggle_flips_the_mode_and_tells_the_admin(self):
        update = admin_update(user=make_user(998877, "admin_boss"))
        with as_admin_chat(), eventbrite_credentials(), patch("bot.handlers.control.logger") as mock_logger:
            await bot_eventbrite_only_toggle_command(update, make_context())
            self.assertTrue(runtime_state.eventbrite_only)
            self.assertIn("ATTIVA", update.message.reply_text.call_args.args[0])
            self.assertTrue(any("998877" in msg and "ON" in msg for msg in _info_messages(mock_logger)))

            await bot_eventbrite_only_toggle_command(update, make_context())
            self.assertFalse(runtime_state.eventbrite_only)
            self.assertIn("DISATTIVATA", update.message.reply_text.call_args.args[0])

    async def test_without_eventbrite_nothing_changes(self):
        update = admin_update()
        with as_admin_chat(), patched_config(EVENTBRITE_TOKEN=None):
            await bot_eventbrite_only_toggle_command(update, make_context())
        self.assertFalse(runtime_state.eventbrite_only)
        self.assertIn("non è configurato", update.message.reply_text.call_args.args[0])

    async def test_status_shows_the_mode(self):
        update = admin_update()
        with as_admin_chat():
            await bot_status_command(update, make_context())
            self.assertIn("normale", update.message.reply_text.call_args.args[0])
            runtime_state.eventbrite_only = True
            await bot_status_command(update, make_context())
            self.assertIn("SOLO EVENTBRITE", update.message.reply_text.call_args.args[0])

    async def test_outsiders_cannot_toggle_it(self):
        update = admin_update()
        with patch("bot.common.auth.config.ADMIN_CHAT_ID", "12345"), eventbrite_credentials():
            await bot_eventbrite_only_toggle_command(update, make_context())
        self.assertFalse(runtime_state.eventbrite_only)


class TestEventbriteVenueCommand(unittest.IsolatedAsyncioTestCase):
    NAMES = {"v1": "Gilda", "v2": "To Play"}

    def setUp(self):
        for patcher in (patch.object(runtime_state, "eventbrite_venue", None),
                        patch.object(runtime_state, "venue_names", dict(self.NAMES))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def two_venues(self):
        return eventbrite_credentials(EVENTBRITE_VENUE_ID="v1", EVENTBRITE_VENUE_ID_ALTERNATIVES=["v2"])

    def labels(self, markup):
        return [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]

    async def test_lists_the_venues_with_the_default_tagged_and_the_current_marked(self):
        update = admin_update()
        with as_admin_chat(), self.two_venues():
            await bot_eventbrite_venue_command(update, make_context())
            self.assertEqual(self.labels(update.message.reply_text.call_args.kwargs["reply_markup"]),
                             [("✅ Gilda (predefinito)", "ebvenue_v1"), ("To Play", "ebvenue_v2")])

    async def test_a_single_venue_has_nothing_to_choose(self):
        update = admin_update()
        with as_admin_chat(), eventbrite_credentials(EVENTBRITE_VENUE_ID="v1"):
            await bot_eventbrite_venue_command(update, make_context())
        self.assertIn("una sola sede", update.message.reply_text.call_args.args[0])

    async def test_without_eventbrite_it_says_so(self):
        update = admin_update()
        with as_admin_chat(), patched_config(EVENTBRITE_TOKEN=None):
            await bot_eventbrite_venue_command(update, make_context())
        self.assertIn("non è configurato", update.message.reply_text.call_args.args[0])

    async def test_picking_a_venue_sets_it_for_new_events(self):
        _update, query = callback_update("ebvenue_v2")
        with as_admin_chat(), self.two_venues():
            await handle_venue_pick(query, make_context(), "v2")
        self.assertEqual(runtime_state.eventbrite_venue, "v2")
        text = query.edit_message_text.call_args.args[0]
        self.assertIn("To Play", text)
        self.assertIn(("✅ To Play", "ebvenue_v2"), self.labels(query.edit_message_text.call_args.kwargs["reply_markup"]))

    async def test_an_unknown_venue_is_refused(self):
        _update, query = callback_update("ebvenue_zzz")
        with as_admin_chat(), self.two_venues():
            await handle_venue_pick(query, make_context(), "zzz")
        self.assertIsNone(runtime_state.eventbrite_venue)
        self.assertTrue(query.answer.call_args.kwargs["show_alert"])

    async def test_outsiders_cannot_pick(self):
        _update, query = callback_update("ebvenue_v2", chat_id=777)
        with as_admin_chat(), self.two_venues():
            await handle_venue_pick(query, make_context(), "v2")
        self.assertIsNone(runtime_state.eventbrite_venue)

    async def test_status_shows_the_venue_only_with_several(self):
        update = admin_update()
        with as_admin_chat(), self.two_venues():
            await bot_status_command(update, make_context())
            self.assertIn("Sede Eventbrite: Gilda", update.message.reply_text.call_args.args[0])
        with as_admin_chat(), eventbrite_credentials(EVENTBRITE_VENUE_ID="v1"):
            await bot_status_command(update, make_context())
            self.assertNotIn("Sede", update.message.reply_text.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
