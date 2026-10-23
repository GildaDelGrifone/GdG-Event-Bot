import os
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta
from unittest.mock import patch

import core.db as db
from bot.service.eventbrite_cleanup import delete_cancelled_eventbrite_events
from core.eventbrite import EventbriteError
from tests.support.config import as_admin_chat, eventbrite_credentials
from tests.support.db import TempDBMixin, create_event
from tests.support.images import image_file
from tests.support.telegram import ADMIN_CHAT_ID, make_bot


def day(delta_days=0):
    return (datetime.now() + timedelta(days=delta_days)).strftime("%d-%m-%Y")


class CleanupCase(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        stack = ExitStack()
        stack.enter_context(eventbrite_credentials())
        stack.enter_context(as_admin_chat())
        self.addCleanup(stack.close)
        self.bot = make_bot()
        self.delete = patch("bot.service.eventbrite_cleanup.delete_eventbrite_event").start()
        self.addCleanup(patch.stopall)

    def make_event(self, eb_status, status="approved", delta_days=0, eb_id=None, **overrides):
        event_id = create_event(status=status, normalized_date=day(delta_days),
                                date=f"Venerdì {day(delta_days)} 21:00", **overrides)
        db.update_event_field(event_id, "admin_message_id", 500 + event_id)
        db.set_eventbrite_info(event_id, eventbrite_event_id=eb_id or f"eb{event_id}", eventbrite_status=eb_status,
                               eventbrite_url="https://eventbrite.example/e/x")
        return event_id

    def texts(self):
        return [c.kwargs["text"] for c in self.bot.send_message.call_args_list]

    def cards(self):
        return {c.kwargs["message_id"]: c.kwargs["reply_markup"] for c in self.bot.edit_message_reply_markup.call_args_list}

    @staticmethod
    def callbacks(keyboard):
        return [b.callback_data for row in keyboard.inline_keyboard for b in row]


class TestDeletion(CleanupCase):
    async def test_cancelled_approved_event_is_deleted_forgotten_and_gets_the_publish_button_back(self):
        event_id = self.make_event("canceled")

        await delete_cancelled_eventbrite_events(self.bot)

        self.delete.assert_called_once_with(f"eb{event_id}")
        event = db.get_event(event_id)
        self.assertIsNone(event["eventbrite_event_id"])
        self.assertIsNone(event["eventbrite_status"])
        self.assertEqual(event["status"], "approved")
        self.assertIn(f"eb_publish_{event_id}", self.callbacks(self.cards()[500 + event_id]))
        self.assertEqual(self.texts(), [f"🧹 Eliminati da Eventbrite 1 eventi annullati: #{event_id} Avventura D&D"])
        self.assertEqual(self.bot.send_message.call_args.kwargs["chat_id"], ADMIN_CHAT_ID)

    async def test_unpublished_event_cancelled_on_telegram_is_deleted_and_telegram_is_untouched(self):
        image = image_file(self.temp_dir.name, "poster.jpg", 400, 300)
        event_id = self.make_event("unpublished", image_path=image, message_link="https://t.me/c/1/2",
                                   telegram_message_id=77)
        db.book_seat(event_id, 1, username="mario")
        db.update_event_status(event_id, "cancelled")  # cancelled on Telegram after the booking

        await delete_cancelled_eventbrite_events(self.bot)

        self.delete.assert_called_once()
        event = db.get_event(event_id)
        self.assertIsNone(event["eventbrite_event_id"])
        # Telegram: event, reservation, image and posts are exactly as before
        self.assertEqual((event["status"], event["telegram_message_id"], event["message_link"]),
                         ("cancelled", 77, "https://t.me/c/1/2"))
        self.assertEqual(len(db.get_reservations_for_event(event_id)), 1)
        self.assertTrue(os.path.exists(image))
        self.assertEqual([c.kwargs["chat_id"] for c in self.bot.send_message.call_args_list], [ADMIN_CHAT_ID])
        self.assertEqual({c.kwargs["chat_id"] for c in self.bot.edit_message_reply_markup.call_args_list}, {ADMIN_CHAT_ID})
        self.bot.delete_message.assert_not_called()
        self.bot.edit_message_text.assert_not_called()
        self.bot.edit_message_caption.assert_not_called()
        self.assertIn(f"reactivate_event_{event_id}", self.callbacks(self.cards()[500 + event_id]))

    async def test_earlier_events_are_cleaned_up_but_future_ones_wait_for_their_day(self):
        past = self.make_event("canceled", delta_days=-3)
        future = self.make_event("canceled", delta_days=2)

        await delete_cancelled_eventbrite_events(self.bot)

        self.delete.assert_called_once_with(f"eb{past}")
        self.assertIsNone(db.get_event(past)["eventbrite_event_id"])
        self.assertEqual(db.get_event(future)["eventbrite_event_id"], f"eb{future}")

        self.delete.reset_mock()
        await delete_cancelled_eventbrite_events(self.bot, today=datetime.now() + timedelta(days=2))
        self.delete.assert_called_once_with(f"eb{future}")

    async def test_only_cancelled_unpublished_and_closed_events_are_candidates(self):
        live = self.make_event("live")
        draft = self.make_event("draft")
        await delete_cancelled_eventbrite_events(self.bot)
        self.delete.assert_not_called()
        self.assertEqual(db.get_event(live)["eventbrite_status"], "live")
        self.assertEqual(db.get_event(draft)["eventbrite_status"], "draft")
        self.assertEqual(self.texts(), [])


class TestKeptEvents(CleanupCase):
    async def test_closed_events_are_kept_reported_and_not_deleted(self):
        event_id = self.make_event("closed", status="cancelled")

        await delete_cancelled_eventbrite_events(self.bot)

        self.delete.assert_not_called()
        self.assertEqual(db.get_event(event_id)["eventbrite_status"], "closed")
        self.assertEqual(self.texts(), [f"⚠️ Non eliminati da Eventbrite: #{event_id} Avventura D&D (ordini ancora da annullare)"])

    async def test_a_refusal_keeps_the_event_and_reports_it(self):
        event_id = self.make_event("canceled")
        self.delete.side_effect = EventbriteError(400, "CANNOT_DELETE", "has orders")

        await delete_cancelled_eventbrite_events(self.bot)

        self.assertEqual(db.get_event(event_id)["eventbrite_event_id"], f"eb{event_id}")
        self.assertEqual(self.texts(), [f"⚠️ Non eliminati da Eventbrite: #{event_id} Avventura D&D (Eventbrite ha rifiutato: CANNOT_DELETE)"])
        self.bot.edit_message_reply_markup.assert_not_called()

    async def test_an_event_already_deleted_by_hand_counts_as_deleted(self):
        event_id = self.make_event("canceled")
        for error in (EventbriteError(404, "NOT_FOUND", ""), EventbriteError(404, "HTTP_404", "")):
            with self.subTest(error=error.error):
                db.set_eventbrite_info(event_id, eventbrite_event_id=f"eb{event_id}", eventbrite_status="canceled")
                self.delete.side_effect = error
                await delete_cancelled_eventbrite_events(self.bot)
                self.assertIsNone(db.get_event(event_id)["eventbrite_event_id"])

    async def test_the_rate_limit_stops_the_run_and_forgets_nothing(self):
        first, second = self.make_event("canceled"), self.make_event("canceled")
        self.delete.side_effect = EventbriteError(429, "HIT_RATE_LIMIT", "slow down")

        await delete_cancelled_eventbrite_events(self.bot)

        self.assertEqual(self.delete.call_count, 1)
        for event_id in (first, second):
            self.assertEqual(db.get_event(event_id)["eventbrite_event_id"], f"eb{event_id}")
        self.assertEqual(self.texts(), [])

    async def test_an_unexpected_error_on_one_event_does_not_stop_the_others(self):
        first, second = self.make_event("canceled"), self.make_event("canceled")
        self.delete.side_effect = [RuntimeError("boom"), True]

        await delete_cancelled_eventbrite_events(self.bot)

        self.assertEqual(db.get_event(first)["eventbrite_event_id"], f"eb{first}")
        self.assertIsNone(db.get_event(second)["eventbrite_event_id"])
        (text,) = self.texts()
        self.assertIn(f"🧹 Eliminati da Eventbrite 1 eventi annullati: #{second}", text)
        self.assertIn(f"⚠️ Non eliminati da Eventbrite: #{first} Avventura D&D (errore: boom)", text)

    async def test_mixed_results_are_reported_in_one_message(self):
        deleted = self.make_event("canceled")
        kept = self.make_event("closed", status="cancelled")
        await delete_cancelled_eventbrite_events(self.bot)
        (text,) = self.texts()
        self.assertEqual(text.count("\n"), 1)
        self.assertIn(f"#{deleted}", text.split("\n")[0])
        self.assertIn(f"#{kept}", text.split("\n")[1])


class TestSwitches(CleanupCase):
    async def test_nothing_to_do_means_no_message(self):
        await delete_cancelled_eventbrite_events(self.bot)
        self.bot.send_message.assert_not_called()
        self.delete.assert_not_called()

    async def test_disabled_integration_or_setting_does_nothing(self):
        event_id = self.make_event("canceled")
        with eventbrite_credentials(EVENTBRITE_TOKEN=None):
            await delete_cancelled_eventbrite_events(self.bot)
        with eventbrite_credentials(EVENTBRITE_DELETE_CANCELLED=False):
            await delete_cancelled_eventbrite_events(self.bot)
        self.delete.assert_not_called()
        self.assertEqual(db.get_event(event_id)["eventbrite_event_id"], f"eb{event_id}")

    async def test_deletions_are_silent_when_cleanup_notifications_are_off(self):
        event_id = self.make_event("canceled")
        with eventbrite_credentials(EVENTBRITE_CLEANUP_NOTIFICATIONS=False):
            await delete_cancelled_eventbrite_events(self.bot)
        self.delete.assert_called_once_with(f"eb{event_id}")
        self.assertIsNone(db.get_event(event_id)["eventbrite_event_id"])
        self.bot.send_message.assert_not_called()

    async def test_kept_events_are_still_reported_when_cleanup_notifications_are_off(self):
        self.make_event("canceled")
        kept = self.make_event("closed", status="cancelled")
        with eventbrite_credentials(EVENTBRITE_CLEANUP_NOTIFICATIONS=False):
            await delete_cancelled_eventbrite_events(self.bot)
        self.assertEqual(self.texts(), [f"⚠️ Non eliminati da Eventbrite: #{kept} Avventura D&D (ordini ancora da annullare)"])

    async def test_works_without_a_bot(self):
        event_id = self.make_event("canceled")
        await delete_cancelled_eventbrite_events(None)
        self.delete.assert_called_once()
        self.assertIsNone(db.get_event(event_id)["eventbrite_event_id"])

    async def test_harmless_telegram_errors_on_the_admin_card_are_ignored(self):
        event_id = self.make_event("canceled")
        self.bot.edit_message_reply_markup.side_effect = Exception("Bad Request: message to edit not found")
        await delete_cancelled_eventbrite_events(self.bot)
        self.assertIsNone(db.get_event(event_id)["eventbrite_event_id"])
        self.assertEqual(len(self.texts()), 1)

    async def test_a_failing_summary_message_does_not_raise(self):
        self.make_event("canceled")
        self.bot.send_message.side_effect = Exception("telegram down")
        await delete_cancelled_eventbrite_events(self.bot)  # must not raise


if __name__ == "__main__":
    unittest.main()
