import unittest
from unittest.mock import patch

import core.db as db
from bot import state
from bot.state import BotRuntimeState, load_persisted_state, reset_persisted_state, set_persisted
from tests.support.config import patched_config
from tests.support.db import TempDBMixin


class TestPersistedState(TempDBMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        patcher = patch.object(state, "runtime_state", BotRuntimeState())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_switches_survive_a_restart(self):
        set_persisted("is_paused", True)
        set_persisted("eventbrite_only", True)
        set_persisted("eventbrite_venue", "v2")
        set_persisted("eventbrite_booking_notifications", False)
        with patch.object(state, "runtime_state", BotRuntimeState()):  # a fresh process
            load_persisted_state()
            self.assertTrue(state.runtime_state.is_paused)
            self.assertTrue(state.runtime_state.eventbrite_only)
            self.assertEqual(state.runtime_state.eventbrite_venue, "v2")
            self.assertFalse(state.runtime_state.eventbrite_booking_notifications)

    def test_never_set_switches_keep_the_env_default(self):
        with patched_config(EVENTBRITE_ONLY_MODE=True), patch.object(state, "runtime_state", BotRuntimeState()):
            load_persisted_state()
            self.assertTrue(state.runtime_state.eventbrite_only)
            self.assertFalse(state.runtime_state.is_paused)
            self.assertIsNone(state.runtime_state.eventbrite_venue)
        self.assertEqual(db.get_setting("eventbrite_only", "unset"), "unset")


    def test_reset_clears_the_saved_switches_and_restores_the_env_defaults(self):
        for name, value in (("is_paused", True), ("eventbrite_only", False), ("eventbrite_venue", "v2"),
                            ("eventbrite_booking_notifications", False)):
            set_persisted(name, value)
        with patched_config(EVENTBRITE_ONLY_MODE=True, EVENTBRITE_BOOKING_NOTIFICATIONS=True):
            self.assertTrue(reset_persisted_state())
        current = state.runtime_state
        self.assertEqual((current.is_paused, current.eventbrite_only, current.eventbrite_venue,
                          current.eventbrite_booking_notifications), (False, True, None, True))
        for name in state.PERSISTED_SETTINGS:
            self.assertEqual(db.get_setting(name, "unset"), "unset")

    def test_reset_reports_a_database_failure(self):
        set_persisted("is_paused", True)
        with patch("bot.state.clear_settings", return_value=False):
            self.assertFalse(reset_persisted_state())
        self.assertFalse(state.runtime_state.is_paused)


if __name__ == "__main__":
    unittest.main()
