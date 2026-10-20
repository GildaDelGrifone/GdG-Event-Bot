import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import bot.callbacks.router as router


class TestCallbackRouter(unittest.IsolatedAsyncioTestCase):
    async def test_dispatches_payload_after_prefix(self):
        handler = AsyncMock()
        update = MagicMock()
        update.callback_query.data = "sub_inc_12_34"
        with patch.object(router, "CALLBACK_ROUTES", (("sub_dec_", AsyncMock()), ("sub_inc_", handler))):
            await router.handle_callback_query(update, MagicMock())
        handler.assert_awaited_once()
        self.assertEqual(handler.call_args.args[2], "12_34")

    def test_prefixes_do_not_shadow_each_other(self):
        prefixes = [p for p, _ in router.CALLBACK_ROUTES]
        for i, earlier in enumerate(prefixes):
            for later in prefixes[i + 1:]:
                self.assertFalse(later.startswith(earlier), f"{earlier!r} would swallow {later!r}")


class TestEventbriteRoutes(unittest.TestCase):
    def test_eventbrite_prefixes_are_routed_to_their_handlers(self):
        from bot.callbacks import events
        routes = dict(router.CALLBACK_ROUTES)
        self.assertIs(routes["publish_eb_event_"], events.handle_publish_event_with_eventbrite)
        self.assertIs(routes["eb_publish_"], events.handle_eventbrite_publish)
        self.assertIs(routes["eb_recreate_"], events.handle_eventbrite_recreate)
        self.assertIs(routes["cancel_event_"], events.handle_cancel_event)
        self.assertIs(routes["cancel_confirm_"], events.handle_cancel_confirm)
        self.assertIs(routes["cancel_abort_"], events.handle_cancel_abort)
        self.assertIs(routes["eb_cancel_retry_"], events.handle_eventbrite_cancel_retry)

    def test_each_callback_data_resolves_to_exactly_one_route(self):
        prefixes = [p for p, _ in router.CALLBACK_ROUTES]
        for data in ("publish_event_1", "publish_eb_event_1", "eb_publish_1", "eb_recreate_1", "cancel_event_1", "cancel_confirm_1", "cancel_abort_1", "eb_cancel_retry_1", "book_1", "unbook_1"):
            with self.subTest(data=data):
                self.assertEqual(len([p for p in prefixes if data.startswith(p)]), 1)


if __name__ == "__main__":
    unittest.main()
