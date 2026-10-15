import unittest

import core.db as db
from bot.callbacks.notices import format_subscribers_tags, send_cancellation_notice, send_reactivation_notice
from tests.support.config import patched_config
from tests.support.db import TempDBMixin, create_subscribed_event
from tests.support.telegram import make_context


class TestSubscribersTags(unittest.TestCase):
    def test_subscribers_tags_deduplicate(self):
        res = [{"username": "Mario"}, {"username": "@mario"}, {"full_name": "Anna"}, {}]
        self.assertEqual(format_subscribers_tags(res), "@Mario, Anna")

    def test_subscriber_tags_formatting(self):
        reservations = [
            {"username": "alice", "user_id": 11},
            {"username": "@bob", "user_id": 22},
            {"username": "alice", "user_id": 11},
            {"username": "", "user_id": 33},
        ]
        tags = format_subscribers_tags(reservations)
        self.assertIn("@alice", tags)
        self.assertIn("@bob", tags)
        self.assertIn("tg://user?id=33", tags)
        self.assertEqual(tags.count("@alice"), 1)

    def test_format_subscribers_tags_no_at_for_non_username(self):
        reservations = [
            {"username": "steucestari", "user_id": 1609031146, "full_name": None},
            {"username": None, "user_id": 8893283822, "full_name": "Lorenzo Duarte"},
            {"username": "ChicoMalo96", "user_id": 297895076, "full_name": None},
        ]
        tags = format_subscribers_tags(reservations)
        self.assertIn("@steucestari", tags)
        self.assertIn("@ChicoMalo96", tags)
        self.assertNotIn("@Lorenzo", tags)
        self.assertIn('<a href="tg://user?id=8893283822">Lorenzo Duarte</a>', tags)


class TestCancellationNotices(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_cancellation_and_reactivation_notifications(self):
        event_id = create_subscribed_event()
        context = make_context()
        send_message = context.bot.send_message
        ev = db.get_event(event_id)
        ev_linked = {**ev, "message_link": "https://t.me/c/123/456"}

        with patched_config(DISCUSSION_GROUP_ID="-100123456"):
            await send_cancellation_notice(context, ev)
            send_message.assert_called_once()
            call_kwargs = send_message.call_args[1]
            self.assertEqual(call_kwargs["chat_id"], -100123456)
            self.assertIn("ANNULLATO", call_kwargs["text"])
            self.assertIn("@mario", call_kwargs["text"])
            self.assertIn("<b>Avventura D&amp;D</b>", call_kwargs["text"])
            self.assertEqual(call_kwargs.get("parse_mode"), "HTML")
            self.assertTrue(call_kwargs.get("disable_web_page_preview"))

            # Cancellation with message_link
            send_message.reset_mock()
            await send_cancellation_notice(context, ev_linked)
            self.assertIn('<a href="https://t.me/c/123/456"><b>Avventura D&amp;D</b></a>', send_message.call_args[1]["text"])

            send_message.reset_mock()
            await send_reactivation_notice(context, ev)
            send_message.assert_called_once()
            call_kwargs = send_message.call_args[1]
            self.assertIn("RIATTIVATO", call_kwargs["text"])
            self.assertIn("@mario", call_kwargs["text"])
            self.assertIn("<b>Avventura D&amp;D</b>", call_kwargs["text"])
            self.assertEqual(call_kwargs.get("parse_mode"), "HTML")
            self.assertTrue(call_kwargs.get("disable_web_page_preview"))

            # Reactivation with message_link
            send_message.reset_mock()
            await send_reactivation_notice(context, ev_linked)
            self.assertIn('<a href="https://t.me/c/123/456"><b>Avventura D&amp;D</b></a>', send_message.call_args[1]["text"])

            # Without subscribers there is nobody to notify
            db.admin_remove_subscriber(event_id, "mario")
            send_message.reset_mock()
            await send_cancellation_notice(context, ev)
            call_kwargs = send_message.call_args[1]
            self.assertIn("ANNULLATO", call_kwargs["text"])
            self.assertNotIn("Iscritti avvisati", call_kwargs["text"])

            send_message.reset_mock()
            await send_reactivation_notice(context, ev)
            call_kwargs = send_message.call_args[1]
            self.assertIn("RIATTIVATO", call_kwargs["text"])
            self.assertNotIn("Iscritti prenotati", call_kwargs["text"])


if __name__ == "__main__":
    unittest.main()
