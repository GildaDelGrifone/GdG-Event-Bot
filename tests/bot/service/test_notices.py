import unittest

import core.db as db
from bot.service.notices import send_admin_action_notice
from tests.support.config import patched_config
from tests.support.db import TempDBMixin, create_no_username_event, create_subscribed_event, create_unpublished_event
from tests.support.telegram import make_context, make_user


class TestSendAdminActionNotice(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.context = make_context()
        self.send_message = self.context.bot.send_message
        config_patch = patched_config(DISCUSSION_GROUP_ID="-100123456")
        config_patch.__enter__()
        self.addCleanup(config_patch.__exit__, None, None, None)

    async def _notice(self, event, **kwargs):
        self.send_message.reset_mock()
        await send_admin_action_notice(self.context, event, **kwargs)
        return self.send_message

    async def test_send_admin_action_notice_direct(self):
        ev = db.get_event(create_subscribed_event())
        admin_user = make_user(username="head_admin", first_name="Super")

        # 1. Add single seat
        send_message = await self._notice(ev, target_username="luigi", action="add", seats=1, admin_user=admin_user)
        send_message.assert_called_once()
        call_kwargs = send_message.call_args[1]
        self.assertEqual(call_kwargs["chat_id"], -100123456)
        self.assertIn("admin degli eventi", call_kwargs["text"].lower())
        self.assertIn("@head_admin", call_kwargs["text"])
        self.assertIn("Aggiunto 1 posto", call_kwargs["text"])
        self.assertIn("@luigi", call_kwargs["text"])

        # 2. Add multiple seats
        send_message = await self._notice(ev, target_username="toad", action="add", seats=3, admin_user=None)
        send_message.assert_called_once()
        call_kwargs = send_message.call_args[1]
        self.assertIn("admin degli eventi", call_kwargs["text"].lower())
        self.assertIn("Aggiunti 3 posti", call_kwargs["text"])
        self.assertIn("@toad", call_kwargs["text"])

        # 3. Remove single seat
        send_message = await self._notice(ev, target_username="luigi", action="remove", seats=1, admin_user=admin_user)
        send_message.assert_called_once()
        call_kwargs = send_message.call_args[1]
        self.assertIn("admin degli eventi", call_kwargs["text"].lower())
        self.assertIn("Rimosso 1 posto", call_kwargs["text"])
        self.assertIn("@luigi", call_kwargs["text"])

        # 4. Remove multiple seats
        send_message = await self._notice(ev, target_user_id=777, action="remove", seats=2, admin_user=admin_user)
        send_message.assert_called_once()
        call_kwargs = send_message.call_args[1]
        self.assertIn("admin degli eventi", call_kwargs["text"].lower())
        self.assertIn("Rimossi 2 posti", call_kwargs["text"])
        self.assertIn('tg://user?id=777', call_kwargs["text"])
        self.assertIn('<b>Avventura D&amp;D</b>', call_kwargs["text"])

        # 5. Event WITH message_link -> the title is bold and linked, not appended on a new line
        ev_with_link = {**ev, "message_link": "https://t.me/c/123/456"}
        send_message = await self._notice(ev_with_link, target_username="luigi", action="add", seats=1,
                                          admin_user=admin_user)
        send_message.assert_called_once()
        call_kwargs = send_message.call_args[1]
        self.assertIn('<a href="https://t.me/c/123/456"><b>Avventura D&amp;D</b></a>', call_kwargs["text"])
        self.assertNotIn("\nhttps://t.me/c/123/456", call_kwargs["text"])

    async def test_send_admin_action_notice_for_user_without_username(self):
        event = db.get_event(create_no_username_event())

        send_message = await self._notice(
            event,
            target_username=None,
            target_full_name="Lorenzo Duarte",
            target_user_id=8893283822,
            action="add",
            seats=1,
            admin_user=make_user(username="admin_user", first_name="Admin"),
        )
        send_message.assert_called_once()
        text = send_message.call_args[1]["text"]
        self.assertNotIn("@Lorenzo", text)
        self.assertIn('<a href="tg://user?id=8893283822">Lorenzo Duarte</a>', text)

    async def test_events_never_posted_on_telegram_get_no_group_notice(self):
        event = {**db.get_event(create_no_username_event()), "telegram_message_id": None}
        send_message = await self._notice(event, target_username="luigi", action="add", seats=1,
                                          admin_user=make_user(username="admin_user", first_name="Admin"))
        send_message.assert_not_called()

    async def test_send_admin_action_notice_direct_unpublished_ignored(self):
        pending_event_id = create_unpublished_event()
        self.assertEqual(db.get_event(pending_event_id)["status"], "pending")
        ev = db.get_event(pending_event_id)
        admin_user = make_user(username="chief_admin", first_name="Chief")
        notice = dict(target_username="player1", action="add", seats=1, admin_user=admin_user)

        # 1. Pending event with no telegram_message_id
        await send_admin_action_notice(self.context, ev, **notice)
        self.send_message.assert_not_called()

        # 2. Pending event even if telegram_message_id is set
        await send_admin_action_notice(self.context, {**ev, "telegram_message_id": 998877}, **notice)
        self.send_message.assert_not_called()

        # 3. Discarded event
        await send_admin_action_notice(self.context, {**ev, "status": "discarded"}, **notice)
        self.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
