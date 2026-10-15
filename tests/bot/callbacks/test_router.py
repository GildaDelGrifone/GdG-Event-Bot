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


if __name__ == "__main__":
    unittest.main()
