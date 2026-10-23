import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import core.db as db
import bot.service.eventbrite_poll as poller
from bot.service.eventbrite_poll import poll_eventbrite_bookings
from core.eventbrite import EventbriteError
from tests.support.config import as_admin_chat, eventbrite_credentials, patched_config
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import ADMIN_CHAT_ID, make_bot

DISCUSSION_CHAT = -100777


class PollCase(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        stack = ExitStack()
        stack.enter_context(eventbrite_credentials())
        stack.enter_context(as_admin_chat(DISCUSSION_GROUP_ID=str(DISCUSSION_CHAT)))
        self.addCleanup(stack.close)
        self.bot = make_bot()
        self.orders = {}
        self.eb_status = "live"
        self.sold = None  # None: the Eventbrite response carries no ticket classes (the poller then always fetches orders)
        poller._last_full_fetch.clear()
        poller._mismatch_logged.clear()
        self.get_event_mock = patch("bot.service.eventbrite_poll.get_eventbrite_event", side_effect=self.eb_event).start()
        self.orders_mock = patch("bot.service.eventbrite_poll.fetch_active_orders",
                                 side_effect=lambda eb_id: dict(self.orders)).start()
        self.update_messages = patch("bot.service.eventbrite_poll.update_event_messages", new_callable=AsyncMock).start()
        self.finish = patch("bot.service.eventbrite_poll.finish_eventbrite_cancellation", new_callable=AsyncMock).start()
        self.addCleanup(patch.stopall)

    def eb_event(self, eb_id):
        event = {"id": eb_id, "status": self.eb_status}
        if self.sold is not None:
            event["ticket_classes"] = [{"name": "Posto", "quantity_total": 4, "quantity_sold": self.sold}]
        return event

    def make_event(self, status="approved", date="06-11-2099", eb_id="eb1", **overrides):
        fields = dict(title="Avventura <D&D>", date=f"Venerdì {date} 21:00", normalized_date=date, max_seats=4,
                      seats="4/4", booked_seats=0)
        event_id = create_event(status=status, **{"telegram_message_id": 900, **fields, **overrides})
        db.update_event_field(event_id, "discussion_message_id", 321)
        if eb_id:
            db.set_eventbrite_info(event_id, eventbrite_event_id=eb_id, eventbrite_status="live")
        return event_id

    def admin_texts(self):
        return [c.kwargs["text"] for c in self.bot.send_message.call_args_list if c.kwargs["chat_id"] == ADMIN_CHAT_ID]

    def discussion_calls(self):
        return [c for c in self.bot.send_message.call_args_list if c.kwargs["chat_id"] == DISCUSSION_CHAT]


class TestDiff(PollCase):
    async def test_new_order_updates_seats_posts_and_announces(self):
        event_id = self.make_event()
        self.orders = {"o1": ("Mario <R.>", 2)}

        await poll_eventbrite_bookings(self.bot)

        event = db.get_event(event_id)
        self.assertEqual((event["booked_seats"], event["seats"]), (2, "2/4"))
        self.assertEqual(db.get_eventbrite_reservations(event_id)[0]["full_name"], "Mario <R.>")
        self.update_messages.assert_awaited_once()
        self.assertEqual(self.update_messages.call_args.args[1], event_id)

        (call,) = self.discussion_calls()
        self.assertTrue(call.kwargs["text"].startswith(
            "🎟️ Mario &lt;R.&gt; ha prenotato 2 posti tramite Eventbrite per: <b>Avventura &lt;D&amp;D&gt;</b>"))
        self.assertEqual(call.kwargs["reply_to_message_id"], 321)
        self.assertIsNotNone(event["eventbrite_synced_at"])

    async def test_eventbrite_only_events_are_announced_in_the_admin_chat(self):
        event_id = self.make_event(telegram_message_id=None)
        self.orders = {"o1": ("Mario <R.>", 2)}

        await poll_eventbrite_bookings(self.bot)

        self.assertEqual(self.discussion_calls(), [])
        (call,) = [c for c in self.bot.send_message.call_args_list if c.kwargs["chat_id"] == ADMIN_CHAT_ID]
        self.assertTrue(call.kwargs["text"].startswith("🎟️ Mario &lt;R.&gt; ha prenotato 2 posti tramite Eventbrite"))
        self.assertEqual(call.kwargs["parse_mode"], "HTML")
        self.assertEqual(db.get_event(event_id)["booked_seats"], 2)

        self.bot.send_message.reset_mock()
        self.orders = {}
        await poll_eventbrite_bookings(self.bot)
        self.assertIn("ha liberato 2 posti (Eventbrite)", self.admin_texts()[0])

    async def test_eventbrite_only_announcements_follow_the_notifications_switch(self):
        self.make_event(telegram_message_id=None)
        self.orders = {"o1": ("Mario R.", 1)}

        with patched_config(EVENTBRITE_BOOKING_NOTIFICATIONS=False):
            await poll_eventbrite_bookings(self.bot)

        self.assertEqual(self.admin_texts(), [])

    async def test_announcements_can_be_turned_off_while_seats_still_sync(self):
        event_id = self.make_event()
        self.orders = {"o1": ("Mario R.", 1)}

        with patched_config(EVENTBRITE_BOOKING_NOTIFICATIONS=False):
            await poll_eventbrite_bookings(self.bot)

        self.assertEqual(self.discussion_calls(), [])
        self.assertEqual(db.get_event(event_id)["booked_seats"], 1)
        self.update_messages.assert_awaited_once()

    async def test_unchanged_orders_do_nothing_but_record_the_poll(self):
        event_id = self.make_event()
        self.orders = {"o1": ("Mario R.", 2)}
        await poll_eventbrite_bookings(self.bot)
        self.update_messages.reset_mock()
        self.bot.send_message.reset_mock()

        await poll_eventbrite_bookings(self.bot)

        self.update_messages.assert_not_awaited()
        self.bot.send_message.assert_not_called()
        self.assertEqual(db.get_event(event_id)["booked_seats"], 2)

    async def test_more_fewer_and_gone_orders(self):
        event_id = self.make_event(max_seats=10, seats="10/10")
        self.orders = {"o1": ("Mario R.", 2), "o2": ("Anna B.", 3)}
        await poll_eventbrite_bookings(self.bot)
        self.bot.send_message.reset_mock()

        self.orders = {"o1": ("Mario R.", 3), "o2": ("Anna B.", 1)}  # +1 for Mario, -2 for Anna
        await poll_eventbrite_bookings(self.bot)
        texts = [c.kwargs["text"] for c in self.discussion_calls()]
        self.assertEqual(len(texts), 2)
        self.assertIn("🎟️ Mario R. ha prenotato 1 posto tramite Eventbrite", texts[0])
        self.assertIn("❌ Anna B. ha liberato 2 posti (Eventbrite) per:", texts[1])
        self.assertEqual(db.get_event(event_id)["booked_seats"], 4)

        self.bot.send_message.reset_mock()
        self.orders = {"o1": ("Mario R.", 3)}  # Anna's order disappeared (cancelled by the attendee)
        await poll_eventbrite_bookings(self.bot)
        (call,) = self.discussion_calls()
        self.assertIn("❌ Anna B. ha liberato 1 posto (Eventbrite)", call.kwargs["text"])
        event = db.get_event(event_id)
        self.assertEqual((event["booked_seats"], event["seats"]), (3, "7/10"))
        self.assertEqual(len(db.get_eventbrite_reservations(event_id)), 1)

    async def test_telegram_reservations_are_never_touched(self):
        event_id = self.make_event()
        db.book_seat(event_id, 1, username="tg")
        self.orders = {"o1": ("Mario R.", 1)}
        await poll_eventbrite_bookings(self.bot)
        self.orders = {}
        await poll_eventbrite_bookings(self.bot)

        self.assertEqual(db.get_event(event_id)["booked_seats"], 1)
        self.assertEqual([r["username"] for r in db.get_reservations_for_event(event_id)], ["tg"])

    async def test_overbooking_alerts_the_admins(self):
        event_id = self.make_event(max_seats=2, seats="2/2")
        db.book_seat(event_id, 1, username="a")
        db.book_seat(event_id, 2, username="b")
        self.orders = {"o1": ("Mario R.", 1)}

        await poll_eventbrite_bookings(self.bot)

        self.assertIn(f"⚠️ Overbooking su #{event_id}: 3/2 (prenotazione Eventbrite arrivata in contemporanea). Ultima prenotazione Telegram: @b.",
                      self.admin_texts())

    async def test_poll_event_now_syncs_a_single_event(self):
        event_id = self.make_event()
        self.orders = {"o1": ("Mario R.", 2)}

        await poller.poll_event_now(self.bot, event_id)

        self.assertEqual(db.get_event(event_id)["booked_seats"], 2)

    async def test_poll_event_now_ignores_untracked_events(self):
        event_id = self.make_event(eb_id=None)
        await poller.poll_event_now(self.bot, event_id)
        self.get_event_mock.assert_not_called()

    async def test_no_overbooking_alert_within_capacity(self):
        self.make_event()
        self.orders = {"o1": ("Mario R.", 4)}
        await poll_eventbrite_bookings(self.bot)
        self.assertEqual(self.admin_texts(), [])

    async def test_cancelled_events_sync_seats_without_announcements(self):
        event_id = self.make_event(status="cancelled")
        self.orders = {"o1": ("Mario R.", 1)}
        await poll_eventbrite_bookings(self.bot)
        self.assertEqual(db.get_event(event_id)["booked_seats"], 1)
        self.assertEqual(self.discussion_calls(), [])


class TestCancellationDetection(PollCase):
    async def test_cancel_confirmed_for_a_telegram_cancelled_event(self):
        event_id = self.make_event(status="cancelled")
        db.set_eventbrite_info(event_id, eventbrite_status="closed")
        self.eb_status = "canceled"

        await poll_eventbrite_bookings(self.bot)
        await poll_eventbrite_bookings(self.bot)  # second pass must not repeat the message

        self.assertEqual(db.get_event(event_id)["eventbrite_status"], "canceled")
        self.assertEqual(self.admin_texts(),
                         [f"✅ Evento #{event_id} annullato su Eventbrite (iscritti avvisati da Eventbrite)"])

    async def test_an_event_deleted_by_hand_is_unlinked_once_and_no_longer_polled(self):
        event_id = self.make_event()
        db.update_event_field(event_id, "admin_message_id", 777)
        self.get_event_mock.side_effect = EventbriteError(404, "NOT_FOUND", "The event does not exist")

        with self.assertNoLogs("bot.service.eventbrite_poll", level="ERROR"):
            await poll_eventbrite_bookings(self.bot)

        self.assertIsNone(db.get_event(event_id)["eventbrite_event_id"])
        admin_calls = [c for c in self.bot.send_message.call_args_list if c.kwargs["chat_id"] == ADMIN_CHAT_ID]
        self.assertEqual(len(admin_calls), 1)
        self.assertIn("eliminato su Eventbrite", admin_calls[0].kwargs["text"])
        self.assertEqual(admin_calls[0].kwargs.get("reply_to_message_id"), 777)

        self.get_event_mock.reset_mock()
        await poll_eventbrite_bookings(self.bot)  # unlinked: not tracked any more
        self.get_event_mock.assert_not_called()

    async def test_other_fetch_errors_keep_the_link(self):
        event_id = self.make_event()
        self.get_event_mock.side_effect = EventbriteError(500, "SERVER_ERROR", "boom")
        await poll_eventbrite_bookings(self.bot)
        self.assertEqual(db.get_event(event_id)["eventbrite_event_id"], "eb1")
        self.assertEqual(self.admin_texts(), [])

    async def test_events_already_cancelled_on_eventbrite_are_not_polled(self):
        event_id = self.make_event()
        db.set_eventbrite_info(event_id, eventbrite_status="canceled")
        await poll_eventbrite_bookings(self.bot)
        self.get_event_mock.assert_not_called()
        self.orders_mock.assert_not_called()

    async def test_warning_when_eventbrite_cancelled_but_telegram_is_active(self):
        event_id = self.make_event()
        self.eb_status = "canceled"
        await poll_eventbrite_bookings(self.bot)
        self.assertEqual(self.admin_texts(), [f"⚠️ Evento #{event_id} annullato su Eventbrite ma attivo su Telegram"])
        self.assertEqual(db.get_event(event_id)["eventbrite_status"], "canceled")

    async def test_admin_notices_reply_to_the_admin_card(self):
        event_id = self.make_event()
        db.update_event_field(event_id, "admin_message_id", 777)
        self.eb_status = "canceled"
        await poll_eventbrite_bookings(self.bot)
        admin_calls = [c for c in self.bot.send_message.call_args_list if c.kwargs["chat_id"] == ADMIN_CHAT_ID]
        self.assertEqual([c.kwargs.get("reply_to_message_id") for c in admin_calls], [777])


class TestCycle(PollCase):
    async def test_only_tracked_events_are_polled(self):
        tracked = self.make_event(eb_id="eb1")
        self.make_event(eb_id=None)
        self.make_event(eb_id="eb-old", date="01-01-2020")
        self.make_event(eb_id="eb-pending", status="pending")

        await poll_eventbrite_bookings(self.bot)

        self.assertEqual([c.args[0] for c in self.get_event_mock.call_args_list], ["eb1"])
        self.assertEqual(db.get_event(tracked)["eventbrite_event_id"], "eb1")

    async def test_rate_limit_stops_the_cycle(self):
        self.make_event(eb_id="eb1")
        self.make_event(eb_id="eb2")
        self.get_event_mock.side_effect = EventbriteError(429, "HIT_RATE_LIMIT", "slow down")

        await poll_eventbrite_bookings(self.bot)

        self.assertEqual(self.get_event_mock.call_count, 1)

    async def test_other_errors_only_skip_that_event(self):
        first = self.make_event(eb_id="eb1")
        second = self.make_event(eb_id="eb2")
        self.get_event_mock.side_effect = [
            EventbriteError(500, "SERVER_ERROR", "boom"), {"id": "eb2", "status": "live"},
        ]
        self.orders = {"o1": ("Mario R.", 1)}

        await poll_eventbrite_bookings(self.bot)

        self.assertEqual(self.get_event_mock.call_count, 2)
        self.assertEqual(db.get_event(first)["booked_seats"], 0)
        self.assertEqual(db.get_event(second)["booked_seats"], 1)

    async def test_unexpected_exceptions_are_contained(self):
        self.make_event(eb_id="eb1")
        self.orders_mock.side_effect = RuntimeError("bug")
        await poll_eventbrite_bookings(self.bot)  # must not raise

    async def test_disabled_integration_polls_nothing(self):
        self.make_event()
        with eventbrite_credentials(EVENTBRITE_TOKEN=None):
            await poll_eventbrite_bookings(self.bot)
        self.get_event_mock.assert_not_called()

    async def test_the_context_only_exposes_the_bot(self):
        self.make_event()
        self.orders = {"o1": ("Mario R.", 1)}
        await poll_eventbrite_bookings(self.bot)
        ctx = self.update_messages.call_args.args[0]
        self.assertIs(ctx.bot, self.bot)


class TestAutoCompleteCancellation(PollCase):
    def closed_event(self, status="cancelled"):
        event_id = self.make_event(status=status)
        db.set_eventbrite_info(event_id, eventbrite_status="closed")
        return event_id

    async def test_closed_event_without_orders_is_completed(self):
        event_id = self.closed_event()
        await poll_eventbrite_bookings(self.bot)
        self.finish.assert_awaited_once()
        ctx, event, chat = self.finish.call_args.args
        self.assertIs(ctx.bot, self.bot)
        self.assertEqual((event["id"], chat), (event_id, ADMIN_CHAT_ID))
        self.assertTrue(self.finish.call_args.kwargs["from_poller"])

    async def test_last_order_cancelled_from_the_dashboard_triggers_completion(self):
        event_id = self.closed_event()
        self.orders = {"o1": ("Mario R.", 1)}
        await poll_eventbrite_bookings(self.bot)
        self.finish.assert_not_awaited()

        self.orders = {}
        await poll_eventbrite_bookings(self.bot)
        self.finish.assert_awaited_once()
        self.assertEqual(db.get_event(event_id)["booked_seats"], 0)

    async def test_eventbrite_only_cancellation_is_completed_too(self):
        event_id = self.closed_event(status="approved")
        await poll_eventbrite_bookings(self.bot)
        self.finish.assert_awaited_once()
        self.assertEqual(self.finish.call_args.args[1]["id"], event_id)

    async def test_not_triggered_for_live_events(self):
        self.make_event(status="cancelled")  # eventbrite_status 'live'
        self.make_event(status="approved")
        await poll_eventbrite_bookings(self.bot)
        self.finish.assert_not_awaited()


class TestEventbriteOnlyCancellation(PollCase):
    async def test_order_cancellations_are_not_announced_while_telegram_stays_active(self):
        event_id = self.make_event()
        self.orders = {"o1": ("Mario R.", 2)}
        await poll_eventbrite_bookings(self.bot)
        db.set_eventbrite_info(event_id, eventbrite_status="closed")
        self.bot.send_message.reset_mock()

        self.orders = {}  # the admin cancelled the order from the dashboard
        await poll_eventbrite_bookings(self.bot)

        self.assertEqual(self.discussion_calls(), [])
        event = db.get_event(event_id)
        self.assertEqual((event["status"], event["booked_seats"]), ("approved", 0))  # seats are free again on Telegram

    async def test_eventbrite_side_cancel_of_a_closed_event_is_confirmed_not_warned(self):
        event_id = self.make_event()
        db.set_eventbrite_info(event_id, eventbrite_status="closed")
        self.eb_status = "canceled"
        await poll_eventbrite_bookings(self.bot)
        self.assertEqual(self.admin_texts(),
                         [f"✅ Evento #{event_id} annullato su Eventbrite (iscritti avvisati da Eventbrite)"])


class TestQuantitySoldShortcut(PollCase):
    """The orders call is skipped while quantity_sold equals the Eventbrite seats we hold."""

    def setUp(self):
        super().setUp()
        self.clock = 1000.0
        patch("bot.service.eventbrite_poll._now", side_effect=lambda: self.clock).start()

    async def poll(self, advance_minutes=0):
        self.clock += advance_minutes * 60
        await poll_eventbrite_bookings(self.bot)

    async def test_unchanged_totals_skip_the_orders_call(self):
        event_id = self.make_event()
        self.sold = 0
        await self.poll()  # first poll of an event is always a full check
        self.assertEqual(self.orders_mock.call_count, 1)

        for _ in range(3):
            await self.poll(advance_minutes=2)

        self.assertEqual(self.orders_mock.call_count, 1)  # three more polls, one call each: the event only
        self.assertEqual(self.get_event_mock.call_count, 4)
        self.update_messages.assert_not_awaited()
        self.assertIsNotNone(db.get_event(event_id)["eventbrite_synced_at"])

    async def test_a_new_booking_is_detected_through_quantity_sold(self):
        event_id = self.make_event()
        self.sold = 0
        await self.poll()
        self.orders_mock.reset_mock()

        self.sold, self.orders = 2, {"o1": ("Mario R.", 2)}
        await self.poll(advance_minutes=2)

        self.orders_mock.assert_called_once()
        self.assertEqual(db.get_event(event_id)["booked_seats"], 2)
        (call,) = self.discussion_calls()
        self.assertIn("Mario R. ha prenotato 2 posti tramite Eventbrite", call.kwargs["text"])

        self.orders_mock.reset_mock()
        await self.poll(advance_minutes=2)  # totals agree again
        self.orders_mock.assert_not_called()

    async def test_a_cancellation_is_detected_through_a_lower_quantity_sold(self):
        event_id = self.make_event()
        self.sold, self.orders = 2, {"o1": ("Mario R.", 2)}
        await self.poll()
        self.orders_mock.reset_mock()
        self.bot.send_message.reset_mock()

        self.sold, self.orders = 0, {}
        await self.poll(advance_minutes=2)

        self.orders_mock.assert_called_once()
        self.assertEqual(db.get_event(event_id)["booked_seats"], 0)
        (call,) = self.discussion_calls()
        self.assertIn("ha liberato 2 posti (Eventbrite)", call.kwargs["text"])

    async def test_a_swap_with_the_same_total_is_only_caught_by_the_full_check(self):
        event_id = self.make_event()
        self.sold, self.orders = 1, {"o1": ("Mario R.", 1)}
        await self.poll()
        self.orders_mock.reset_mock()

        self.orders = {"o2": ("Anna B.", 1)}  # Mario cancelled and Anna booked: quantity_sold is still 1
        await self.poll(advance_minutes=2)
        await self.poll(advance_minutes=20)
        self.orders_mock.assert_not_called()
        self.assertEqual([r["full_name"] for r in db.get_eventbrite_reservations(event_id)], ["Mario R."])

        await self.poll(advance_minutes=10)  # 32 minutes after the last full check
        self.orders_mock.assert_called_once()
        self.assertEqual([r["full_name"] for r in db.get_eventbrite_reservations(event_id)], ["Anna B."])

    async def test_the_full_check_interval_is_configurable_and_zero_means_every_poll(self):
        self.make_event()
        self.sold = 0
        with patched_config(EVENTBRITE_FULL_SYNC_MINUTES=5):
            await self.poll()
            await self.poll(advance_minutes=4)
            self.assertEqual(self.orders_mock.call_count, 1)
            await self.poll(advance_minutes=2)
            self.assertEqual(self.orders_mock.call_count, 2)

        self.orders_mock.reset_mock()
        with patched_config(EVENTBRITE_FULL_SYNC_MINUTES=0):
            await self.poll(advance_minutes=1)
            await self.poll(advance_minutes=1)
        self.assertEqual(self.orders_mock.call_count, 2)

    async def test_without_ticket_classes_every_poll_fetches_the_orders(self):
        self.make_event()
        self.sold = None
        for _ in range(3):
            await self.poll(advance_minutes=2)
        self.assertEqual(self.orders_mock.call_count, 3)

    async def test_events_are_tracked_independently(self):
        first, second = self.make_event(eb_id="eb1"), self.make_event(eb_id="eb2")
        self.sold = 0
        await self.poll()
        self.orders_mock.reset_mock()
        await self.poll(advance_minutes=2)
        self.orders_mock.assert_not_called()
        self.assertEqual({first, second}, set(poller._last_full_fetch))

    async def test_a_persistent_mismatch_falls_back_to_fetching_and_is_logged_once(self):
        self.make_event()
        self.sold, self.orders = 3, {"o1": ("Mario R.", 2)}  # e.g. a hold that never shows up as an order

        with patch("bot.service.eventbrite_poll.logger") as mock_logger:
            for _ in range(3):
                await self.poll(advance_minutes=2)

        self.assertEqual(self.orders_mock.call_count, 3)  # fetched on every poll while they disagree
        self.assertEqual(mock_logger.warning.call_count, 1)

        self.sold = 2  # they agree again
        await self.poll(advance_minutes=2)
        self.orders_mock.reset_mock()
        await self.poll(advance_minutes=2)
        self.orders_mock.assert_not_called()

    async def test_orders_lagging_behind_quantity_sold_are_retried_on_the_next_poll(self):
        event_id = self.make_event()
        self.sold, self.orders = 1, {}  # Eventbrite is eventually consistent: the order is not listed yet
        await self.poll()
        self.assertEqual(db.get_event(event_id)["booked_seats"], 0)

        self.orders = {"o1": ("Mario R.", 1)}
        await self.poll(advance_minutes=2)
        self.assertEqual(db.get_event(event_id)["booked_seats"], 1)

    async def test_closed_cancellation_is_completed_without_fetching_orders(self):
        event_id = self.make_event(status="cancelled")
        db.set_eventbrite_info(event_id, eventbrite_status="closed")
        self.sold = 0
        poller._last_full_fetch[event_id] = self.clock  # a full check just happened

        await self.poll(advance_minutes=2)

        self.orders_mock.assert_not_called()
        self.finish.assert_awaited_once()
        self.assertTrue(self.finish.call_args.kwargs["from_poller"])

    async def test_closed_cancellation_with_orders_left_is_not_completed(self):
        event_id = self.make_event(status="cancelled")
        db.set_eventbrite_info(event_id, eventbrite_status="closed")
        self.sold, self.orders = 1, {"o1": ("Mario R.", 1)}
        await self.poll()  # stores the seat
        self.orders_mock.reset_mock()

        await self.poll(advance_minutes=2)  # sold == stored == 1: no fetch, and orders certainly exist

        self.orders_mock.assert_not_called()
        self.finish.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
