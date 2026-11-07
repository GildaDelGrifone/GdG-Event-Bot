import unittest
from unittest.mock import patch

import core.db as db
from bot import state
from bot.state import BotRuntimeState, load_persisted_state, set_persisted
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
        with patch.object(state, "runtime_state", BotRuntimeState()):  # a fresh process
            load_persisted_state()
            self.assertTrue(state.runtime_state.is_paused)
            self.assertTrue(state.runtime_state.eventbrite_only)
            self.assertEqual(state.runtime_state.eventbrite_venue, "v2")

    def test_never_set_switches_keep_the_env_default(self):
        with patched_config(EVENTBRITE_ONLY_MODE=True), patch.object(state, "runtime_state", BotRuntimeState()):
            load_persisted_state()
            self.assertTrue(state.runtime_state.eventbrite_only)
            self.assertFalse(state.runtime_state.is_paused)
            self.assertIsNone(state.runtime_state.eventbrite_venue)
        self.assertEqual(db.get_setting("eventbrite_only", "unset"), "unset")


if __name__ == "__main__":
    unittest.main()
