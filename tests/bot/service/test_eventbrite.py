import os
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import core.db as db
from bot.service import eventbrite as service
from core.eventbrite import EventbriteError
from tests.support.config import as_admin_chat, eventbrite_credentials
from tests.support.db import TempDBMixin, create_event
from tests.support.images import image_file
from tests.support.telegram import ADMIN_CHAT_ID, make_context

PATCHED = (
    "create_event", "update_event", "publish_event", "unpublish_event", "cancel_event", "set_description",
    "create_free_ticket_class", "update_ticket_quantity", "upload_logo", "fetch_active_orders", "refund_order",
)
ADMIN = int(ADMIN_CHAT_ID)


class EventbriteServiceCase(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    """Approved events dated in 2099, Eventbrite configured, every core.eventbrite call mocked where it is used."""

    def setUp(self):
        super().setUp()
        stack = ExitStack()
        stack.enter_context(eventbrite_credentials())
        stack.enter_context(as_admin_chat())
        self.addCleanup(stack.close)
        self.context = make_context()
        self.mocks = {}
        for name in PATCHED:
            patcher = patch(f"bot.service.eventbrite.{name}")
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)
        self.mocks["create_event"].return_value = {"id": "eb1", "url": "https://eventbrite.example/e/eb1"}
        self.mocks["create_free_ticket_class"].return_value = {"id": "tc1"}
        self.mocks["publish_event"].return_value = True
        self.mocks["unpublish_event"].return_value = True
        self.mocks["cancel_event"].return_value = True
        self.mocks["upload_logo"].return_value = "media1"
        self.mocks["set_description"].side_effect = lambda eb_id, modules, version: version
        self.mocks["fetch_active_orders"].return_value = {}
        update_patch = patch("bot.service.posts.update_event_messages", new_callable=AsyncMock)
        self.update_messages = update_patch.start()
        self.addCleanup(update_patch.stop)

    def make_event(self, status="approved", **overrides):
        fields = dict(title="Avventura", date="Venerdì 06-11-2099 21:00", normalized_date="06-11-2099", system="D&D 5e",
                      host="DM", seats="4/4", booked_seats=0, max_seats=4, description="Una storia", is_roleplay=1)
        event_id = create_event(status=status, **{**fields, **overrides})
        db.update_event_field(event_id, "admin_message_id", 500)
        return event_id

    def link(self, event_id, **info):
        db.set_eventbrite_info(event_id, **{
            "eventbrite_event_id": "eb1", "eventbrite_url": "https://eventbrite.example/e/eb1",
            "eventbrite_ticket_class_id": "tc1", "eventbrite_status": "live", "eventbrite_quantity_total": 4,
            "eventbrite_content_version": 1, **info,
        })

    def texts(self):
        return [call.kwargs["text"] for call in self.context.bot.send_message.call_args_list]

    def no_http(self):
        for name in PATCHED:
            self.mocks[name].assert_not_called()


class TestPublish(EventbriteServiceCase):
    async def test_happy_path_runs_the_steps_in_order_and_stores_the_ids(self):
        image = image_file(self.temp_dir.name, "poster.jpg", 400, 300)
        event_id = self.make_event(image_path=image)
        manager = MagicMock()
        steps = ("create_event", "create_free_ticket_class", "upload_logo", "update_event", "set_description",
                 "publish_event")
        for name in steps:
            manager.attach_mock(self.mocks[name], name)

        await service.publish_event_to_eventbrite(self.context, event_id, ADMIN)

        self.assertEqual([call[0] for call in manager.mock_calls], list(steps))
        event = db.get_event(event_id)
        self.assertEqual(
            (event["eventbrite_event_id"], event["eventbrite_url"], event["eventbrite_ticket_class_id"],
             event["eventbrite_status"], event["eventbrite_quantity_total"], event["eventbrite_content_version"]),
            ("eb1", "https://eventbrite.example/e/eb1", "tc1", "live", 4, 1))
        self.assertEqual(self.mocks["create_free_ticket_class"].call_args.args[:2], ("eb1", 4))
        self.assertEqual(self.mocks["update_event"].call_args.args, ("eb1", {"logo_id": "media1"}))
        self.assertEqual(self.mocks["set_description"].call_args.args[2], 1)
        self.assertIn("✅ Evento pubblicato su Eventbrite: https://eventbrite.example/e/eb1", self.texts())
        self.update_messages.assert_awaited_once_with(self.context, event_id)

    async def test_admin_card_gets_the_eventbrite_button_from_the_stored_message_id(self):
        event_id = self.make_event()
        await service.publish_event_to_eventbrite(self.context, event_id, ADMIN)

        edit = self.context.bot.edit_message_reply_markup
        edit.assert_awaited_once()
        self.assertEqual((edit.call_args.kwargs["chat_id"], edit.call_args.kwargs["message_id"]), (ADMIN_CHAT_ID, 500))
        buttons = [b for row in edit.call_args.kwargs["reply_markup"].inline_keyboard for b in row]
        self.assertIn("https://www.eventbrite.com/myevent?eid=eb1", [b.url for b in buttons])

    async def test_logo_failure_is_only_a_warning(self):
        image = image_file(self.temp_dir.name, "poster.jpg", 400, 300)
        event_id = self.make_event(image_path=image)
        self.mocks["upload_logo"].side_effect = EventbriteError(400, "BAD_IMAGE", "nope")

        await service.publish_event_to_eventbrite(self.context, event_id, ADMIN)

        self.assertEqual(db.get_event(event_id)["eventbrite_status"], "live")
        self.assertTrue(any(t.startswith("⚠️ Logo non caricato") for t in self.texts()))
        self.mocks["publish_event"].assert_called_once()

    async def test_no_logo_call_without_an_image_file(self):
        event_id = self.make_event(image_path=os.path.join(self.temp_dir.name, "missing.jpg"))
        await service.publish_event_to_eventbrite(self.context, event_id, ADMIN)
        self.mocks["upload_logo"].assert_not_called()

    async def test_failure_leaves_a_draft_and_the_retry_resumes_it(self):
        event_id = self.make_event()
        self.mocks["create_free_ticket_class"].side_effect = EventbriteError(500, "SERVER_ERROR", "boom")

        await service.publish_event_to_eventbrite(self.context, event_id, ADMIN)

        event = db.get_event(event_id)
        self.assertEqual((event["eventbrite_event_id"], event["eventbrite_status"]), ("eb1", "draft"))
        self.assertTrue(any("pubblicazione fallita" in t for t in self.texts()))
        self.mocks["publish_event"].assert_not_called()

        self.mocks["create_free_ticket_class"].side_effect = None
        self.mocks["create_free_ticket_class"].return_value = {"id": "tc1"}
        await service.publish_event_to_eventbrite(self.context, event_id, ADMIN)

        self.mocks["create_event"].assert_called_once()  # not created twice
        self.assertEqual(db.get_event(event_id)["eventbrite_status"], "live")

    async def test_resume_skips_the_ticket_class_and_bumps_the_description_version(self):
        event_id = self.make_event()
        self.link(event_id, eventbrite_status="draft", eventbrite_content_version=1)

        await service.publish_event_to_eventbrite(self.context, event_id, ADMIN)

        self.mocks["create_event"].assert_not_called()
        self.mocks["create_free_ticket_class"].assert_not_called()
        self.assertEqual(self.mocks["set_description"].call_args.args[2], 2)
        self.assertEqual(db.get_event(event_id)["eventbrite_content_version"], 2)
        self.mocks["publish_event"].assert_called_once_with("eb1")

    async def test_already_live_replies_with_the_existing_link(self):
        event_id = self.make_event()
        self.link(event_id)

        await service.publish_event_to_eventbrite(self.context, event_id, ADMIN)

        self.no_http()
        self.assertEqual(self.texts(), ["ℹ️ Evento già pubblicato su Eventbrite: https://eventbrite.example/e/eb1"])

    async def test_refused_for_a_zero_zero_completo_event(self):
        event_id = self.make_event(seats="0/0 Completo", max_seats=0)

        await service.publish_event_to_eventbrite(self.context, event_id, ADMIN)

        self.no_http()
        self.assertEqual(self.texts(), [
            "❌ Eventbrite: l'evento non ha posti liberi (0/0), non c'è nulla da prenotare su Eventbrite. "
            "Aggiorna i posti con /event_edit_seats e riprova con [🎟️ Pubblica su Eventbrite]."])
        self.assertIsNone(db.get_event(event_id)["eventbrite_event_id"])

    async def test_refused_for_an_event_fully_booked_on_telegram(self):
        event_id = self.make_event(max_seats=2, seats="2/2")
        db.book_seat(event_id, 1, username="a")
        db.book_seat(event_id, 2, username="b")

        await service.publish_event_to_eventbrite(self.context, event_id, ADMIN)

        self.no_http()
        self.assertIn("non ha posti liberi (0/2)", self.texts()[0])

    async def test_allowed_for_an_unlimited_event_using_the_configured_capacity(self):
        event_id = self.make_event(max_seats=None, seats="no limit")

        await service.publish_event_to_eventbrite(self.context, event_id, ADMIN)

        self.assertEqual(self.mocks["create_free_ticket_class"].call_args.args[:2], ("eb1", 50))
        self.assertEqual(db.get_event(event_id)["eventbrite_status"], "live")

    async def test_partially_booked_event_publishes_the_remaining_seats(self):
        event_id = self.make_event(max_seats=4)
        db.book_seat(event_id, 1, username="a")

        await service.publish_event_to_eventbrite(self.context, event_id, ADMIN)

        self.assertEqual(self.mocks["create_free_ticket_class"].call_args.args[:2], ("eb1", 3))

    async def test_preconditions(self):
        past = self.make_event(date="Venerdì 06-11-2020 21:00", normalized_date="06-11-2020")
        pending = self.make_event(status="pending")
        for event_id in (past, pending, 999):
            await service.publish_event_to_eventbrite(self.context, event_id, ADMIN)
        self.no_http()
        texts = self.texts()
        self.assertEqual(texts[0], "❌ Eventbrite: data nel passato")
        self.assertIn("deve essere pubblicato su Telegram", texts[1])
        self.assertEqual(texts[2], "❌ Evento #999 non trovato")

    async def test_not_configured(self):
        event_id = self.make_event()
        with eventbrite_credentials(EVENTBRITE_TOKEN=None):
            await service.publish_event_to_eventbrite(self.context, event_id, ADMIN)
        self.no_http()
        self.assertEqual(self.texts(), ["❌ Eventbrite non configurato"])

    async def test_canceled_eventbrite_event_offers_the_recreate_button(self):
        event_id = self.make_event()
        self.link(event_id, eventbrite_status="canceled")

        await service.publish_event_to_eventbrite(self.context, event_id, ADMIN)

        self.no_http()
        markup = self.context.bot.send_message.call_args.kwargs["reply_markup"]
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, f"eb_recreate_{event_id}")

    async def test_recreate_clears_the_old_event_and_publishes_a_new_one(self):
        event_id = self.make_event()
        self.link(event_id, eventbrite_status="canceled", eventbrite_event_id="old")

        await service.recreate_on_eventbrite(self.context, event_id, ADMIN)

        self.assertEqual(self.mocks["create_event"].call_count, 1)
        event = db.get_event(event_id)
        self.assertEqual((event["eventbrite_event_id"], event["eventbrite_status"]), ("eb1", "live"))


class TestSync(EventbriteServiceCase):
    def event(self, event_id):
        return db.get_event(event_id)

    async def test_skips_unlinked_disabled_canceled_and_draft_events(self):
        unlinked = self.make_event()
        await service.sync_eventbrite(self.context, self.event(unlinked), content_changed=True)

        for status in ("canceled", "draft"):
            event_id = self.make_event()
            self.link(event_id, eventbrite_status=status, eventbrite_quantity_total=99)
            await service.sync_eventbrite(self.context, self.event(event_id), content_changed=True)

        disabled = self.make_event()
        self.link(disabled, eventbrite_quantity_total=99)
        with eventbrite_credentials(EVENTBRITE_TOKEN=None):
            await service.sync_eventbrite(self.context, self.event(disabled), content_changed=True)

        self.no_http()

    async def test_unchanged_quantity_makes_no_call(self):
        event_id = self.make_event()
        self.link(event_id, eventbrite_quantity_total=4)
        await service.sync_eventbrite(self.context, self.event(event_id))
        self.no_http()

    async def test_telegram_booking_lowers_the_eventbrite_quantity(self):
        event_id = self.make_event()
        self.link(event_id, eventbrite_quantity_total=4)
        db.book_seat(event_id, 1, username="a")

        await service.sync_eventbrite(self.context, self.event(event_id))

        self.mocks["update_ticket_quantity"].assert_called_once_with("eb1", "tc1", 3)
        self.assertEqual(self.event(event_id)["eventbrite_quantity_total"], 3)
        await service.sync_eventbrite(self.context, self.event(event_id))
        self.mocks["update_ticket_quantity"].assert_called_once()  # cached: no repeat

    async def test_eventbrite_bookings_do_not_change_the_quantity(self):
        event_id = self.make_event()
        self.link(event_id, eventbrite_quantity_total=4)
        db.apply_eventbrite_order(event_id, "o1", "Mario R.", 2)
        await service.sync_eventbrite(self.context, self.event(event_id))
        self.mocks["update_ticket_quantity"].assert_not_called()

    async def test_cancelled_events_do_not_push_capacity(self):
        event_id = self.make_event(status="cancelled")
        self.link(event_id, eventbrite_quantity_total=99)
        await service.sync_eventbrite(self.context, self.event(event_id))
        self.mocks["update_ticket_quantity"].assert_not_called()

    async def test_content_change_updates_the_event_and_the_next_description_version(self):
        event_id = self.make_event()
        self.link(event_id, eventbrite_content_version=3)

        await service.sync_eventbrite(self.context, self.event(event_id), content_changed=True)

        eb_id, payload = self.mocks["update_event"].call_args.args
        self.assertEqual(eb_id, "eb1")
        self.assertEqual(payload["name"], {"html": "Avventura"})
        self.assertEqual(payload["start"]["utc"], "2099-11-06T20:00:00Z")
        self.assertEqual(self.mocks["set_description"].call_args.args[2], 4)
        self.assertEqual(self.event(event_id)["eventbrite_content_version"], 4)

    async def test_date_moved_into_the_past_skips_the_dates_and_warns(self):
        event_id = self.make_event(date="Venerdì 06-11-2020 21:00", normalized_date="06-11-2020")
        self.link(event_id)

        await service.sync_eventbrite(self.context, self.event(event_id), content_changed=True)

        payload = self.mocks["update_event"].call_args.args[1]
        self.assertNotIn("start", payload)
        self.assertNotIn("end", payload)
        self.mocks["set_description"].assert_called_once()
        self.assertTrue(any("data non aggiornata su Eventbrite (data nel passato)" in t for t in self.texts()))

    async def test_image_change_uploads_a_new_logo(self):
        image = image_file(self.temp_dir.name, "new.jpg", 400, 300)
        event_id = self.make_event(image_path=image)
        self.link(event_id)

        await service.sync_eventbrite(self.context, self.event(event_id), image_changed=True)

        self.mocks["upload_logo"].assert_called_once_with(image)
        self.mocks["update_event"].assert_called_once_with("eb1", {"logo_id": "media1"})
        self.mocks["set_description"].assert_not_called()

    async def test_errors_are_reported_to_the_admins_and_never_raised(self):
        event_id = self.make_event()
        self.link(event_id)
        db.book_seat(event_id, 1, username="a")
        self.mocks["update_ticket_quantity"].side_effect = EventbriteError(500, "SERVER_ERROR", "boom")

        await service.sync_eventbrite(self.context, self.event(event_id))

        self.assertTrue(any(t.startswith(f"⚠️ Sync Eventbrite fallita per #{event_id}") for t in self.texts()))


class TestCancel(EventbriteServiceCase):
    def linked_event(self, **info):
        event_id = self.make_event(status="cancelled")
        self.link(event_id, **info)
        return event_id

    async def cancel(self, event_id):
        await service.cancel_on_eventbrite(self.context, db.get_event(event_id))

    async def test_without_orders_the_event_is_unpublished(self):
        event_id = self.linked_event()
        await self.cancel(event_id)

        self.mocks["unpublish_event"].assert_called_once_with("eb1")
        self.mocks["cancel_event"].assert_not_called()
        self.mocks["update_ticket_quantity"].assert_not_called()
        self.assertEqual(db.get_event(event_id)["eventbrite_status"], "unpublished")

    async def test_unpublish_refused_falls_through_to_the_cancel_branch(self):
        event_id = self.linked_event()
        self.mocks["unpublish_event"].side_effect = EventbriteError(400, "CANNOT_UNPUBLISH", "")

        await self.cancel(event_id)

        self.mocks["cancel_event"].assert_called_once_with("eb1")
        self.assertEqual(db.get_event(event_id)["eventbrite_status"], "canceled")

    async def test_with_orders_every_order_is_refunded_then_the_event_is_cancelled(self):
        event_id = self.linked_event()
        self.mocks["fetch_active_orders"].return_value = {"o1": ("Mario R.", 2), "o2": ("Anna B.", 1)}
        manager = MagicMock()
        for name in ("update_ticket_quantity", "update_event", "refund_order", "cancel_event"):
            manager.attach_mock(self.mocks[name], name)

        await self.cancel(event_id)

        self.assertEqual([c[0] for c in manager.mock_calls],
                         ["update_ticket_quantity", "update_event", "refund_order", "refund_order", "cancel_event"])
        self.assertEqual([c.args for c in self.mocks["refund_order"].call_args_list], [("o1",), ("o2",)])
        self.mocks["unpublish_event"].assert_not_called()
        self.mocks["update_ticket_quantity"].assert_called_once_with("eb1", "tc1", 3)
        eb_id, payload = self.mocks["update_event"].call_args.args
        self.assertEqual(payload["name"], {"html": "[ANNULLATO] Avventura"})
        self.assertNotIn("start", payload)
        self.mocks["cancel_event"].assert_called_once_with("eb1")
        event = db.get_event(event_id)
        self.assertEqual((event["eventbrite_status"], event["eventbrite_quantity_total"]), ("canceled", 3))
        self.assertIn(f"✅ Evento #{event_id} annullato anche su Eventbrite (2 prenotazioni rimborsate, "
                      "i partecipanti sono stati avvisati via email)", self.texts())

    async def test_cancel_refused_after_the_refunds_sends_the_dashboard_link_and_marks_the_event_closed(self):
        event_id = self.linked_event()
        self.mocks["fetch_active_orders"].return_value = {"o1": ("Mario R.", 2)}
        self.mocks["cancel_event"].side_effect = EventbriteError(400, "CANNOT_CANCEL", "has orders")

        await self.cancel(event_id)

        self.mocks["refund_order"].assert_called_once_with("o1")
        self.assertEqual(db.get_event(event_id)["eventbrite_status"], "closed")
        call = self.context.bot.send_message.call_args
        self.assertIn("1 prenotazioni Eventbrite rimborsate, ma Eventbrite non permette di annullare", call.kwargs["text"])
        self.assertIn("https://www.eventbrite.com/myevent?eid=eb1", call.kwargs["text"])
        button = call.kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual((button.text, button.url), ("🎟️ Apri dashboard Eventbrite", "https://www.eventbrite.com/myevent?eid=eb1"))

    async def test_a_failed_refund_skips_the_cancel_and_reports_the_counts(self):
        event_id = self.linked_event()
        self.mocks["fetch_active_orders"].return_value = {"o1": ("A", 1), "o2": ("B", 1), "o3": ("C", 1)}
        self.mocks["refund_order"].side_effect = [None, EventbriteError(400, "REFUND_ERROR", "free order"), None]

        await self.cancel(event_id)

        self.assertEqual(self.mocks["refund_order"].call_count, 3)  # keeps going after a failure
        self.mocks["cancel_event"].assert_not_called()
        self.assertEqual(db.get_event(event_id)["eventbrite_status"], "closed")
        call = self.context.bot.send_message.call_args
        self.assertIn("2 prenotazioni Eventbrite rimborsate, 1 non rimborsabili via API", call.kwargs["text"])
        self.assertEqual(call.kwargs["reply_markup"].inline_keyboard[0][0].text, "🎟️ Apri dashboard Eventbrite")

    async def test_rate_limit_stops_the_refunds_and_counts_the_rest_as_failed(self):
        event_id = self.linked_event()
        self.mocks["fetch_active_orders"].return_value = {"o1": ("A", 1), "o2": ("B", 1), "o3": ("C", 1), "o4": ("D", 1)}
        self.mocks["refund_order"].side_effect = [None, EventbriteError(429, "HIT_RATE_LIMIT", "slow"), None, None]

        await self.cancel(event_id)

        self.assertEqual(self.mocks["refund_order"].call_count, 2)
        self.mocks["cancel_event"].assert_not_called()
        self.assertIn("1 prenotazioni Eventbrite rimborsate, 3 non rimborsabili via API", self.texts()[-1])

    async def test_no_orders_means_no_refunds(self):
        await self.cancel(self.linked_event())
        self.mocks["refund_order"].assert_not_called()

    async def test_nothing_to_do_for_unlinked_or_already_handled_events(self):
        unlinked = self.make_event(status="cancelled")
        await self.cancel(unlinked)
        for status in ("canceled", "draft", "unpublished", "closed"):
            await self.cancel(self.linked_event(eventbrite_status=status))
        self.no_http()

    async def test_api_failure_is_reported_not_raised(self):
        event_id = self.linked_event()
        self.mocks["fetch_active_orders"].side_effect = EventbriteError(500, "SERVER_ERROR", "boom")
        await self.cancel(event_id)
        self.assertTrue(any("Annullamento su Eventbrite fallito" in t for t in self.texts()))


class TestReactivate(EventbriteServiceCase):
    def linked_event(self, **info):
        event_id = self.make_event()
        self.link(event_id, **info)
        return event_id

    async def reactivate(self, event_id):
        await service.reactivate_on_eventbrite(self.context, db.get_event(event_id))

    async def test_unpublished_event_is_republished_with_content_and_capacity(self):
        event_id = self.linked_event(eventbrite_status="unpublished", eventbrite_quantity_total=4)

        await self.reactivate(event_id)

        self.mocks["publish_event"].assert_called_once_with("eb1")
        self.assertEqual(self.mocks["update_event"].call_args.args[1]["name"], {"html": "Avventura"})
        self.mocks["set_description"].assert_called_once()
        self.mocks["update_ticket_quantity"].assert_called_once_with("eb1", "tc1", 4)  # forced even if cached
        self.assertEqual(db.get_event(event_id)["eventbrite_status"], "live")
        self.assertIn(f"✅ Evento #{event_id} riattivato anche su Eventbrite", self.texts())

    async def test_closed_event_gets_its_name_and_capacity_back(self):
        event_id = self.linked_event(eventbrite_status="closed", eventbrite_quantity_total=2)
        db.apply_eventbrite_order(event_id, "o1", "Mario R.", 2)

        await self.reactivate(event_id)

        self.mocks["publish_event"].assert_not_called()
        self.assertEqual(self.mocks["update_event"].call_args.args[1]["name"], {"html": "Avventura"})
        self.mocks["update_ticket_quantity"].assert_called_once_with("eb1", "tc1", 4)
        self.assertEqual(db.get_event(event_id)["eventbrite_status"], "live")

    async def test_canceled_event_cannot_be_revived_and_offers_to_recreate_it(self):
        event_id = self.linked_event(eventbrite_status="canceled")

        await self.reactivate(event_id)

        self.no_http()
        call = self.context.bot.send_message.call_args
        self.assertEqual(call.kwargs["text"], "ℹ️ L'evento era stato annullato su Eventbrite e non può essere riattivato.")
        self.assertEqual(call.kwargs["reply_markup"].inline_keyboard[0][0].callback_data, f"eb_recreate_{event_id}")

    async def test_live_unlinked_and_failing_cases(self):
        await self.reactivate(self.linked_event(eventbrite_status="live"))
        await self.reactivate(self.make_event())
        self.no_http()

        event_id = self.linked_event(eventbrite_status="unpublished")
        self.mocks["publish_event"].side_effect = EventbriteError(400, "CANNOT_PUBLISH", "")
        await self.reactivate(event_id)
        self.assertTrue(any("Riattivazione su Eventbrite fallita" in t for t in self.texts()))
        self.assertEqual(db.get_event(event_id)["eventbrite_status"], "unpublished")


if __name__ == "__main__":
    unittest.main()
