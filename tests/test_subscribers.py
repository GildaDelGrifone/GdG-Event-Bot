import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import core.db as db
from core import config
from bot.callbacks.notices import format_subscribers_tags, send_cancellation_notice, send_reactivation_notice
from bot.callbacks.subscribers import format_subscribers_management_view
from bot.callbacks.router import handle_callback_query
from bot.handlers.subscribers import event_sub_add_command, event_sub_remove_command, handle_admin_reply
from bot.handlers.recap import handle_discussion_forward
from bot.handlers.public import start_command
from bot.keyboards import (
    get_approval_keyboard,
    get_approved_event_keyboard,
    get_cancelled_event_keyboard,
    get_subscribers_management_keyboard,
    get_event_booking_keyboard,
)
from bot.service.notices import send_admin_action_notice
from bot.service.booking import handle_seat_booking, handle_seat_unbooking, format_conflict_warning_message, send_conflict_warning
from utils.templates import (
    format_event_title_link,
    format_event_participants_message,
    format_reservation_subscriber_display,
    recap_generate_text,
    recap_links_text,
)


class TestSubscriberManagement(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = self.test_db_path
        db.init_db()

        self.event_data = {
            "title": "Avventura D&D",
            "date": "Venerdì 21:00",
            "normalized_date": "2026-09-05",
            "system": "D&D 5e",
            "host": "Master John",
            "seats": "4/5",
            "booked_seats": 1,
            "max_seats": 5,
            "description": "Una grande avventura",
            "status": "approved",
        }
        self.event_id = db.insert_event(self.event_data, None, "test original text")
        db.update_event_status(self.event_id, "approved")
        # Add initial reservation
        db.book_seat(self.event_id, 1001, "mario")

    def tearDown(self):
        config.DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()

    def test_db_admin_subscribers(self):
        subs = db.get_reservations_for_event(self.event_id)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["username"], "mario")
        self.assertEqual(subs[0]["seats_booked"], 1)

        # Admin adds new subscriber @luigi with 2 seats
        ok, msg = db.admin_add_subscriber(self.event_id, "@luigi", seats=2)
        self.assertTrue(ok)
        subs = db.get_reservations_for_event(self.event_id)
        self.assertEqual(len(subs), 2)
        luigi = next(s for s in subs if s["username"] == "luigi")
        self.assertEqual(luigi["seats_booked"], 2)

        ev = db.get_event(self.event_id)
        self.assertEqual(ev["booked_seats"], 4)
        self.assertEqual(ev["seats"], "1/5")

        # Admin adds 1 seat to luigi
        ok, msg = db.admin_add_seat(self.event_id, luigi["id"])
        self.assertTrue(ok)
        ev = db.get_event(self.event_id)
        self.assertEqual(ev["booked_seats"], 5)
        self.assertEqual(ev["seats"], "0/5")

        # Admin tries to add another seat beyond max_seats (5) -> should fail
        ok, msg = db.admin_add_seat(self.event_id, luigi["id"])
        self.assertFalse(ok)
        self.assertIn("raggiunta", msg.lower())

        # Admin tries to add subscriber beyond max_seats -> should fail
        ok, msg = db.admin_add_subscriber(self.event_id, "toad", seats=1)
        self.assertFalse(ok)
        self.assertIn("superata", msg.lower())

        # Admin removes 1 seat from luigi
        ok, msg = db.admin_remove_seat(self.event_id, luigi["id"])
        self.assertTrue(ok)
        subs = db.get_reservations_for_event(self.event_id)
        luigi = next(s for s in subs if s["username"] == "luigi")
        self.assertEqual(luigi["seats_booked"], 2)

        # Admin removes subscriber luigi completely
        ok, msg = db.admin_remove_subscriber(self.event_id, "luigi")
        self.assertTrue(ok)
        subs = db.get_reservations_for_event(self.event_id)
        self.assertEqual(len(subs), 1)
    def test_keyboards_structure(self):
        appr_kb = get_approval_keyboard(self.event_id)
        self.assertEqual(len(appr_kb.inline_keyboard), 2)
        self.assertEqual(appr_kb.inline_keyboard[1][0].callback_data, f"manage_subs_{self.event_id}")
        appr_callbacks = [btn.callback_data for row in appr_kb.inline_keyboard for btn in row]
        self.assertIn(f"publish_event_{self.event_id}", appr_callbacks)
        self.assertIn(f"discard_event_{self.event_id}", appr_callbacks)
        self.assertNotIn(f"cancel_event_{self.event_id}", appr_callbacks)

        approved_kb = get_approved_event_keyboard(self.event_id)
        self.assertEqual(approved_kb.inline_keyboard[0][0].callback_data, f"cancel_event_{self.event_id}")
        self.assertEqual(approved_kb.inline_keyboard[0][1].callback_data, f"manage_subs_{self.event_id}")

        cancelled_kb = get_cancelled_event_keyboard(self.event_id)
        self.assertEqual(cancelled_kb.inline_keyboard[0][0].callback_data, f"reactivate_event_{self.event_id}")
        self.assertEqual(cancelled_kb.inline_keyboard[0][1].callback_data, f"manage_subs_{self.event_id}")

        subs = db.get_reservations_for_event(self.event_id)
        subs_kb = get_subscribers_management_keyboard(self.event_id, subs)
        self.assertTrue(any("sub_inc_" in btn.callback_data for row in subs_kb.inline_keyboard for btn in row))
        self.assertTrue(any("sub_dec_" in btn.callback_data for row in subs_kb.inline_keyboard for btn in row))

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

    async def test_cancellation_and_reactivation_notifications(self):
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        ev = db.get_event(self.event_id)

        with patch("core.config.DISCUSSION_GROUP_ID", "-100123456"):
            await send_cancellation_notice(context, ev)
            context.bot.send_message.assert_called_once()
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertEqual(call_kwargs["chat_id"], -100123456)
            self.assertIn("ANNULLATO", call_kwargs["text"])
            self.assertIn("@mario", call_kwargs["text"])
            self.assertIn("<b>Avventura D&amp;D</b>", call_kwargs["text"])
            self.assertEqual(call_kwargs.get("parse_mode"), "HTML")
            self.assertTrue(call_kwargs.get("disable_web_page_preview"))

            # Test cancellation with message_link
            ev_linked = dict(ev)
            ev_linked["message_link"] = "https://t.me/c/123/456"
            context.bot.send_message.reset_mock()
            await send_cancellation_notice(context, ev_linked)
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertIn('<a href="https://t.me/c/123/456"><b>Avventura D&amp;D</b></a>', call_kwargs["text"])

            context.bot.send_message.reset_mock()
            await send_reactivation_notice(context, ev)
            context.bot.send_message.assert_called_once()
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertIn("RIATTIVATO", call_kwargs["text"])
            self.assertIn("@mario", call_kwargs["text"])
            self.assertIn("<b>Avventura D&amp;D</b>", call_kwargs["text"])
            self.assertEqual(call_kwargs.get("parse_mode"), "HTML")
            self.assertTrue(call_kwargs.get("disable_web_page_preview"))

            # Test reactivation with message_link
            context.bot.send_message.reset_mock()
            await send_reactivation_notice(context, ev_linked)
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertIn('<a href="https://t.me/c/123/456"><b>Avventura D&amp;D</b></a>', call_kwargs["text"])

            db.admin_remove_subscriber(self.event_id, "mario")
            context.bot.send_message.reset_mock()
            await send_cancellation_notice(context, ev)
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertIn("ANNULLATO", call_kwargs["text"])
            self.assertNotIn("Iscritti avvisati", call_kwargs["text"])

            context.bot.send_message.reset_mock()
            await send_reactivation_notice(context, ev)
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertIn("RIATTIVATO", call_kwargs["text"])
            self.assertNotIn("Iscritti prenotati", call_kwargs["text"])

    def test_subscribers_management_view_bold_title(self):
        ev = dict(self.event_data)
        ev["id"] = self.event_id
        ev["message_link"] = "https://t.me/c/123/456"
        reservations = [{"username": "mario", "seats_booked": 1}]
        view = format_subscribers_management_view(ev, reservations)
        self.assertIn('📌 <a href="https://t.me/c/123/456"><b>Avventura D&amp;D</b></a>', view)

        ev_no_link = dict(self.event_data)
        ev_no_link["id"] = self.event_id
        ev_no_link["message_link"] = None
        view_no_link = format_subscribers_management_view(ev_no_link, reservations)
        self.assertIn('📌 <b>Avventura D&amp;D</b>', view_no_link)

    async def test_cancel_and_reactivate_callback_flow(self):
        query = MagicMock()
        query.data = f"cancel_event_{self.event_id}"
        query.message.caption = "Post evento"
        query.message.photo = True
        query.edit_message_caption = AsyncMock()
        query.answer = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        with patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("bot.callbacks.events.update_event_messages", AsyncMock()):
            await handle_callback_query(update, context)
            ev = db.get_event(self.event_id)
            self.assertEqual(ev["status"], "cancelled")
            query.edit_message_caption.assert_called_once()
            call_kb = query.edit_message_caption.call_args[1]["reply_markup"]
            self.assertTrue(any("reactivate_event_" in btn.callback_data for row in call_kb.inline_keyboard for btn in row))

            query.data = f"reactivate_event_{self.event_id}"
            query.edit_message_caption.reset_mock()
            await handle_callback_query(update, context)
            ev = db.get_event(self.event_id)
            self.assertEqual(ev["status"], "approved")
            query.edit_message_caption.assert_called_once()
            call_kb = query.edit_message_caption.call_args[1]["reply_markup"]
            self.assertTrue(any("cancel_event_" in btn.callback_data for row in call_kb.inline_keyboard for btn in row))

    async def test_admin_commands(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.message.reply_to_message = None
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.args = [str(self.event_id), "@peach", "2"]

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.subscribers.update_event_messages", AsyncMock()):
            await event_sub_add_command(update, context)
            update.message.reply_text.assert_called_once()
            self.assertIn("registrato con successo", update.message.reply_text.call_args[0][0])
            subs = db.get_reservations_for_event(self.event_id)
            peach = next(s for s in subs if s["username"] == "peach")
            self.assertEqual(peach["seats_booked"], 2)

            update.message.reply_text.reset_mock()
            context.args = [str(self.event_id), "@peach", "1"]
            await event_sub_remove_command(update, context)
            update.message.reply_text.assert_called_once()
            self.assertIn("Rimossi 1 posto/i", update.message.reply_text.call_args[0][0])
            subs = db.get_reservations_for_event(self.event_id)
            peach = next(s for s in subs if s["username"] == "peach")
            self.assertEqual(peach["seats_booked"], 1)

            update.message.reply_to_message = MagicMock()
            update.message.reply_to_message.text = f"✏️ Invia l'username Telegram, rispondendo a questo messaggio, da aggiungere all'evento #{self.event_id}"
            update.message.text = "@daisy 1"
            update.message.reply_text.reset_mock()
            await handle_admin_reply(update, context)
            update.message.reply_text.assert_called_once()
            self.assertIn("registrato con successo", update.message.reply_text.call_args[0][0])
            subs = db.get_reservations_for_event(self.event_id)
            self.assertTrue(any(s["username"] == "daisy" for s in subs))

    async def test_manage_subs_callbacks(self):
        query = MagicMock()
        query.data = f"manage_subs_{self.event_id}"
        query.message.text = "Post text"
        query.message.chat_id = 999
        query.message.message_id = 123
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        # 1. Open management view from event message
        await handle_callback_query(update, context)
        context.bot.send_message.assert_called_once()
        msg_call = context.bot.send_message.call_args[1]
        self.assertIn("Gestione Iscritti", msg_call["text"])
        self.assertEqual(msg_call["reply_to_message_id"], 123)

        # 2. Refresh view when on management message
        query.message.text = "👥 Gestione Iscritti\n📌 Avventura D&D"
        await handle_callback_query(update, context)
        query.edit_message_text.assert_called_once()

        # 3. sub_inc_
        subs = db.get_reservations_for_event(self.event_id)
        res_id = subs[0]["id"]
        query.data = f"sub_inc_{self.event_id}_{res_id}"
        query.edit_message_text.reset_mock()
        with patch("bot.callbacks.subscribers.update_event_messages", AsyncMock()):
            await handle_callback_query(update, context)
            query.edit_message_text.assert_called_once()
            subs_after = db.get_reservations_for_event(self.event_id)
            self.assertEqual(subs_after[0]["seats_booked"], 2)

        # 4. sub_dec_
        query.data = f"sub_dec_{self.event_id}_{res_id}"
        query.edit_message_text.reset_mock()
        with patch("bot.callbacks.subscribers.update_event_messages", AsyncMock()):
            await handle_callback_query(update, context)
            query.edit_message_text.assert_called_once()
            subs_after = db.get_reservations_for_event(self.event_id)
            self.assertEqual(subs_after[0]["seats_booked"], 1)

        # 5. sub_addnew_
        query.data = f"sub_addnew_{self.event_id}"
        context.bot.send_message.reset_mock()
        await handle_callback_query(update, context)
        context.bot.send_message.assert_called_once()
        self.assertIn("Invia l'username Telegram, rispondendo a questo messaggio, da aggiungere", context.bot.send_message.call_args[1]["text"])

        # 6. close_subs_
        query.data = f"close_subs_{self.event_id}"
        query.message.delete = AsyncMock()
        await handle_callback_query(update, context)
        query.message.delete.assert_called_once()

    async def test_admin_commands_reply_mode(self):
        update = MagicMock()
        update.effective_chat.id = 999
        reply_msg = MagicMock()
        reply_msg.reply_markup.inline_keyboard = [
            [MagicMock(callback_data=f"publish_event_{self.event_id}")]
        ]
        reply_msg.caption = None
        reply_msg.text = None
        reply_msg.message_id = 9999
        update.message.reply_to_message = reply_msg
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.args = ["@bowser", "1"]

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("bot.handlers.subscribers.update_event_messages", AsyncMock()):
            await event_sub_add_command(update, context)
            update.message.reply_text.assert_called_once()
            self.assertIn("registrato con successo", update.message.reply_text.call_args[0][0])
            subs = db.get_reservations_for_event(self.event_id)
            self.assertTrue(any(s["username"] == "bowser" for s in subs))

            # Remove via reply
            update.message.reply_text.reset_mock()
            context.args = ["@bowser"]
            await event_sub_remove_command(update, context)
            update.message.reply_text.assert_called_once()
            self.assertIn("Rimossi", update.message.reply_text.call_args[0][0])
            subs = db.get_reservations_for_event(self.event_id)
            self.assertFalse(any(s["username"] == "bowser" for s in subs))

    async def test_send_admin_action_notice_direct(self):
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        ev = db.get_event(self.event_id)

        admin_user = MagicMock()
        admin_user.username = "head_admin"
        admin_user.first_name = "Super"

        with patch("core.config.DISCUSSION_GROUP_ID", "-100123456"):
            # 1. Add single seat
            await send_admin_action_notice(
                context,
                ev,
                target_username="luigi",
                action="add",
                seats=1,
                admin_user=admin_user,
            )
            context.bot.send_message.assert_called_once()
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertEqual(call_kwargs["chat_id"], -100123456)
            self.assertIn("admin degli eventi", call_kwargs["text"].lower())
            self.assertIn("@head_admin", call_kwargs["text"])
            self.assertIn("Aggiunto 1 posto", call_kwargs["text"])
            self.assertIn("@luigi", call_kwargs["text"])

            # 2. Add multiple seats
            context.bot.send_message.reset_mock()
            await send_admin_action_notice(
                context,
                ev,
                target_username="toad",
                action="add",
                seats=3,
                admin_user=None,
            )
            context.bot.send_message.assert_called_once()
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertIn("admin degli eventi", call_kwargs["text"].lower())
            self.assertIn("Aggiunti 3 posti", call_kwargs["text"])
            self.assertIn("@toad", call_kwargs["text"])

            # 3. Remove single seat
            context.bot.send_message.reset_mock()
            await send_admin_action_notice(
                context,
                ev,
                target_username="luigi",
                action="remove",
                seats=1,
                admin_user=admin_user,
            )
            context.bot.send_message.assert_called_once()
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertIn("admin degli eventi", call_kwargs["text"].lower())
            self.assertIn("Rimosso 1 posto", call_kwargs["text"])
            self.assertIn("@luigi", call_kwargs["text"])

            # 4. Remove multiple seats
            context.bot.send_message.reset_mock()
            await send_admin_action_notice(
                context,
                ev,
                target_user_id=777,
                action="remove",
                seats=2,
                admin_user=admin_user,
            )
            context.bot.send_message.assert_called_once()
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertIn("admin degli eventi", call_kwargs["text"].lower())
            self.assertIn("Rimossi 2 posti", call_kwargs["text"])
            self.assertIn('tg://user?id=777', call_kwargs["text"])
            self.assertIn('<b>Avventura D&amp;D</b>', call_kwargs["text"])

            # 5. Add seat on event WITH message_link -> title should be bold and linked, not appended on new line
            ev_with_link = dict(ev)
            ev_with_link["message_link"] = "https://t.me/c/123/456"
            context.bot.send_message.reset_mock()
            await send_admin_action_notice(
                context,
                ev_with_link,
                target_username="luigi",
                action="add",
                seats=1,
                admin_user=admin_user,
            )
            context.bot.send_message.assert_called_once()
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertIn('<a href="https://t.me/c/123/456"><b>Avventura D&amp;D</b></a>', call_kwargs["text"])
            self.assertNotIn("\nhttps://t.me/c/123/456", call_kwargs["text"])

    async def test_admin_action_notice_on_callback_queries(self):
        query = MagicMock()
        query.message.text = "👥 Gestione Iscritti\n📌 Avventura D&D"
        query.message.chat_id = 999
        query.message.message_id = 123
        query.from_user.username = "table_master"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        subs = db.get_reservations_for_event(self.event_id)
        res_id = subs[0]["id"]

        with patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("bot.callbacks.subscribers.update_event_messages", AsyncMock()):
            # sub_inc_
            query.data = f"sub_inc_{self.event_id}_{res_id}"
            await handle_callback_query(update, context)
            context.bot.send_message.assert_called_once()
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertEqual(call_kwargs["chat_id"], -100123456)
            self.assertIn("admin degli eventi", call_kwargs["text"].lower())
            self.assertIn("@mario", call_kwargs["text"])
            self.assertIn("Aggiunto 1 posto", call_kwargs["text"])

            # sub_dec_
            context.bot.send_message.reset_mock()
            query.data = f"sub_dec_{self.event_id}_{res_id}"
            await handle_callback_query(update, context)
            context.bot.send_message.assert_called_once()
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertEqual(call_kwargs["chat_id"], -100123456)
            self.assertIn("admin degli eventi", call_kwargs["text"].lower())
            self.assertIn("@mario", call_kwargs["text"])
            self.assertIn("Rimosso 1 posto", call_kwargs["text"])

    async def test_admin_action_notice_on_admin_commands(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.effective_user.username = "chief_admin"
        update.message.reply_to_message = None
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.args = [str(self.event_id), "@wario", "2"]

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("bot.handlers.subscribers.update_event_messages", AsyncMock()):
            # /event_sub_add
            await event_sub_add_command(update, context)
            context.bot.send_message.assert_called_once()
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertEqual(call_kwargs["chat_id"], -100123456)
            self.assertIn("admin degli eventi", call_kwargs["text"].lower())
            self.assertIn("@wario", call_kwargs["text"])
            self.assertIn("Aggiunti 2 posti", call_kwargs["text"])
            self.assertIn("@chief_admin", call_kwargs["text"])

            # /event_sub_remove
            context.bot.send_message.reset_mock()
            context.args = [str(self.event_id), "@wario", "1"]
            await event_sub_remove_command(update, context)
            context.bot.send_message.assert_called_once()
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertEqual(call_kwargs["chat_id"], -100123456)
            self.assertIn("admin degli eventi", call_kwargs["text"].lower())
            self.assertIn("@wario", call_kwargs["text"])
            self.assertIn("Rimosso 1 posto", call_kwargs["text"])

            # handle_admin_reply ForceReply
            context.bot.send_message.reset_mock()
            update.message.reply_to_message = MagicMock()
            update.message.reply_to_message.text = f"✏️ Invia l'username Telegram, rispondendo a questo messaggio, da aggiungere all'evento #{self.event_id}"
            update.message.text = "@waluigi 1"
            await handle_admin_reply(update, context)
            context.bot.send_message.assert_called_once()
            call_kwargs = context.bot.send_message.call_args[1]
            self.assertEqual(call_kwargs["chat_id"], -100123456)
            self.assertIn("admin degli eventi", call_kwargs["text"].lower())
            self.assertIn("@waluigi", call_kwargs["text"])
            self.assertIn("Aggiunto 1 posto", call_kwargs["text"])
    def test_get_user_conflicting_events(self):
        # self.event_id is on "2026-09-05" and mario (1001) is booked on it

        # Event 2: Same day, approved
        ev2_data = dict(self.event_data)
        ev2_data["title"] = "Call of Cthulhu"
        ev2_id = db.insert_event(ev2_data, None, "raw text")
        db.update_event_status(ev2_id, "approved")

        # Event 3: Different day ("2026-09-06"), approved
        ev3_data = dict(self.event_data)
        ev3_data["title"] = "Cyberpunk RED"
        ev3_data["normalized_date"] = "2026-09-06"
        ev3_id = db.insert_event(ev3_data, None, "raw text")
        db.update_event_status(ev3_id, "approved")
        db.book_seat(ev3_id, 1001, "mario")

        # Event 4: Same day, but cancelled
        ev4_data = dict(self.event_data)
        ev4_data["title"] = "Vampire V5"
        ev4_id = db.insert_event(ev4_data, None, "raw text")
        db.update_event_status(ev4_id, "cancelled")
        db.book_seat(ev4_id, 1001, "mario")

        # Event 5: Same day, approved, but user unsubscribed
        ev5_data = dict(self.event_data)
        ev5_data["title"] = "Pathfinder 2e"
        ev5_id = db.insert_event(ev5_data, None, "raw text")
        db.update_event_status(ev5_id, "approved")
        db.book_seat(ev5_id, 1001, "mario")
        db.unbook_seat(ev5_id, 1001, "mario")

        # Event 6: Same day written in DD-MM-YYYY format ("05-09-2026")
        ev6_data = dict(self.event_data)
        ev6_data["title"] = "Blades in the Dark"
        ev6_data["normalized_date"] = "05-09-2026"
        ev6_id = db.insert_event(ev6_data, None, "raw text")
        db.update_event_status(ev6_id, "approved")

        # Now test Mario subscribing to ev2:
        conflicts = db.get_user_conflicting_events(ev2_id, user_id=1001, username="mario")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["id"], self.event_id)
        self.assertEqual(conflicts[0]["title"], "Avventura D&D")

        # Test Mario subscribing to ev6 (cross-format DD-MM-YYYY vs YYYY-MM-DD):
        conflicts_ev6 = db.get_user_conflicting_events(ev6_id, user_id=1001, username="mario")
        self.assertEqual(len(conflicts_ev6), 1)
        self.assertEqual(conflicts_ev6[0]["id"], self.event_id)

        # Test querying with only user_id or only username
        conflicts_uid_only = db.get_user_conflicting_events(ev2_id, user_id=1001, username=None)
        self.assertEqual(len(conflicts_uid_only), 1)
        conflicts_uname_only = db.get_user_conflicting_events(ev2_id, user_id=None, username="@mario")
        self.assertEqual(len(conflicts_uname_only), 1)

        # Test self.event_id itself is excluded
        conflicts_self = db.get_user_conflicting_events(self.event_id, user_id=1001, username="mario")
        self.assertEqual(len(conflicts_self), 0)

        # If Mario books ev2 as well, then queries for ev6 (a 3rd event that day):
        db.book_seat(ev2_id, 1001, "mario")
        conflicts_multi = db.get_user_conflicting_events(ev6_id, user_id=1001, username="mario")
        self.assertEqual(len(conflicts_multi), 2)
        conflict_ids = [c["id"] for c in conflicts_multi]
        self.assertIn(self.event_id, conflict_ids)
        self.assertIn(ev2_id, conflict_ids)

    def test_format_conflict_warning_message(self):
        user = MagicMock()
        user.username = "mario"
        user.first_name = "Mario"

        ev1 = {
            "title": "Avventura D&D",
            "system": "D&D 5e",
            "message_link": "https://t.me/c/123/456"
        }
        msg1 = format_conflict_warning_message(user, [ev1])
        self.assertIn("⚠️ <b>Attenzione @mario:</b>", msg1)
        self.assertIn("risulti già iscritto a un altro evento per la stessa data:", msg1)
        self.assertIn('<a href="https://t.me/c/123/456"><b>Avventura D&amp;D</b></a>', msg1)
        self.assertIn("D&amp;D 5e", msg1)
        self.assertIn("La tua prenotazione è stata registrata regolarmente", msg1)
        self.assertIn("liberare il posto", msg1)

        ev2 = {
            "title": "Call of Cthulhu",
            "system": "Horror",
            "message_link": ""
        }
        msg2 = format_conflict_warning_message(user, [ev1, ev2])
        self.assertIn("⚠️ <b>Attenzione @mario:</b>", msg2)
        self.assertIn("risulti già iscritto ad altri 2 eventi per la stessa data:", msg2)
        self.assertIn('<a href="https://t.me/c/123/456"><b>Avventura D&amp;D</b></a>', msg2)
        self.assertIn("<b>Call of Cthulhu</b>", msg2)
        # User without username (first_name only)
        user_no_uname = MagicMock()
        user_no_uname.id = 2003
        user_no_uname.username = None
        user_no_uname.first_name = "Luigi"
        msg3 = format_conflict_warning_message(user_no_uname, [ev1])
        self.assertIn('<a href="tg://user?id=2003">Luigi</a>', msg3)


    async def test_handle_seat_booking_conflict_warning(self):
        # Create second event on the same day
        ev2_data = dict(self.event_data)
        ev2_data["title"] = "Call of Cthulhu"
        ev2_data["message_link"] = "https://t.me/c/123/999"
        ev2_id = db.insert_event(ev2_data, None, "raw text")
        db.update_event_status(ev2_id, "approved")

        # Setup mocks
        user = MagicMock()
        user.id = 1001
        user.username = "mario"
        user.first_name = "Mario"

        query = MagicMock()
        query.message.chat_id = -100123456
        query.message.message_id = 555
        query.answer = AsyncMock()

        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.edit_message_caption = AsyncMock()

        with patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("core.config.PUBLIC_CHANNEL_ID", "-1007890"), \
             patch("bot.service.booking.update_event_messages", AsyncMock()):
            # Mario books ev2 while already booked on self.event_id
            await handle_seat_booking(ev2_id, user, query, context)

            # Reservation succeeds as normal
            res = db.get_reservation_by_user(ev2_id, user_id=1001)
            self.assertIsNotNone(res)
            self.assertEqual(res["seats_booked"], 1)

            # Two messages should be sent to notify_chat:
            # 1. The booking confirmation
            # 2. The conflict warning
            self.assertEqual(context.bot.send_message.call_count, 2)

            first_call_args = context.bot.send_message.call_args_list[0][1]
            self.assertIn("ha prenotato 1 posto", first_call_args["text"])
            self.assertIn('<a href="https://t.me/c/123/999"><b>Call of Cthulhu</b></a>', first_call_args["text"])
            self.assertNotIn("\nhttps://t.me/c/123/999", first_call_args["text"])
            self.assertEqual(first_call_args["parse_mode"], "HTML")

            second_call_args = context.bot.send_message.call_args_list[1][1]
            self.assertIn("Attenzione @mario", second_call_args["text"])
            self.assertIn("<b>Avventura D&amp;D</b>", second_call_args["text"])
            self.assertIn("La tua prenotazione è stata registrata regolarmente", second_call_args["text"])

    async def test_handle_seat_booking_no_conflict(self):
        # Create a new user with no other bookings
        user = MagicMock()
        user.id = 2002
        user.username = "peach"
        user.first_name = "Peach"

        query = MagicMock()
        query.message.chat_id = -100123456
        query.message.message_id = 556
        query.answer = AsyncMock()

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        with patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("core.config.PUBLIC_CHANNEL_ID", "-1007890"), \
             patch("bot.service.booking.update_event_messages", AsyncMock()):
            await handle_seat_booking(self.event_id, user, query, context)

            # Reservation succeeds as normal
            res = db.get_reservation_by_user(self.event_id, user_id=2002)
            self.assertIsNotNone(res)
            self.assertEqual(res["seats_booked"], 1)

            # Only ONE message sent (the booking confirmation), NO warning
            self.assertEqual(context.bot.send_message.call_count, 1)
            call_args = context.bot.send_message.call_args[1]
            self.assertIn("ha prenotato 1 posto", call_args["text"])
            self.assertIn("<b>Avventura D&amp;D</b>", call_args["text"])
            self.assertEqual(call_args["parse_mode"], "HTML")
            self.assertNotIn("Attenzione", call_args["text"])

    async def test_handle_seat_unbooking_formatting(self):
        user = MagicMock()
        user.id = 1001
        user.username = "mario"
        user.first_name = "Mario"

        query = MagicMock()
        query.message.chat_id = -100123456
        query.message.message_id = 777
        query.answer = AsyncMock()

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        ev2_data = dict(self.event_data)
        ev2_data["title"] = "Call of Cthulhu"
        ev2_data["message_link"] = "https://t.me/c/123/999"
        ev2_id = db.insert_event(ev2_data, None, "raw text")
        db.update_event_status(ev2_id, "approved")
        db.book_seat(ev2_id, 1001, "mario")

        with patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("core.config.PUBLIC_CHANNEL_ID", "-1007890"), \
             patch("bot.service.booking.update_event_messages", AsyncMock()):
            await handle_seat_unbooking(ev2_id, user, query, context)

            res = db.get_reservation_by_user(ev2_id, user_id=1001)
            self.assertIsNone(res)

            context.bot.send_message.assert_called_once()
            call_args = context.bot.send_message.call_args[1]
            self.assertIn("ha liberato 1 posto", call_args["text"])
            self.assertIn('<a href="https://t.me/c/123/999"><b>Call of Cthulhu</b></a>', call_args["text"])
            self.assertNotIn("\nhttps://t.me/c/123/999", call_args["text"])
            self.assertEqual(call_args["parse_mode"], "HTML")

    def test_recap_generate_text_event_titles_bold(self):
        events = [
            {
                "title": "Avventura D&D",
                "system": "D&D 5e",
                "booked_seats": 2,
                "max_seats": 5,
                "status": "approved",
            },
            {
                "title": "Cyberpunk Red",
                "system": "Cyberpunk",
                "booked_seats": 0,
                "max_seats": 4,
                "status": "cancelled",
            },
            {
                "title": "One Shot Giochi Liberi",
                "system": None,
                "booked_seats": 3,
                "max_seats": None,
                "status": "approved",
            },
        ]
        text = recap_generate_text("Venerdì", "05-09-2026", events)
        self.assertIn("- <b>Avventura D&amp;D</b> (D&amp;D 5e) : 3/5", text)
        self.assertIn("- ❌ <b>Cyberpunk Red</b> (Cyberpunk) : 0/4 [ANNULLATO]", text)
        self.assertIn("- <b>One Shot Giochi Liberi</b> : Nessun limite (Prenotati: 3)", text)

    def test_recap_links_text_event_titles_bold_and_linked(self):
        events = [
            {
                "title": "Avventura D&D",
                "system": "D&D 5e",
                "message_link": "https://t.me/c/123/456",
                "status": "approved",
            },
            {
                "title": "Call of Cthulhu",
                "system": "CoC",
                "message_link": None,
                "status": "approved",
            },
            {
                "title": "Cancelled Event",
                "system": "Test",
                "message_link": "https://t.me/c/123/789",
                "status": "cancelled",
            },
        ]
        links_text = recap_links_text(events)
        self.assertIn('- <a href="https://t.me/c/123/456"><b>Avventura D&amp;D</b></a> (D&amp;D 5e)', links_text)
        self.assertIn('- <b>Call of Cthulhu</b> (CoC)', links_text)
        self.assertNotIn("Cancelled Event", links_text)

    async def test_publish_recap_does_not_send_links_to_event_channel(self):
        update = MagicMock()
        query = MagicMock()
        query.data = "publish_recap_05-09-2026"
        query.message.chat_id = 9999
        query.message.message_id = 123
        query.message.caption = "Recap caption"
        query.message.text = None
        query.answer = AsyncMock()
        query.edit_message_caption = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query

        context = MagicMock()
        pub_message = MagicMock()
        pub_message.message_id = 777
        context.bot.copy_message = AsyncMock(return_value=pub_message)
        context.bot.send_message = AsyncMock()

        test_events = [
            {
                "id": 1,
                "title": "Avventura D&D",
                "system": "D&D 5e",
                "status": "approved",
                "message_link": "https://t.me/c/123/456",
                "image_path": None,
            }
        ]

        with patch("core.config.PUBLIC_CHANNEL_ID", "-100111111"), \
             patch("bot.callbacks.recap.get_pending_events_for_recap", return_value=test_events), \
             patch("bot.callbacks.recap.generate_wordpress_article", return_value=None), \
             patch("bot.callbacks.recap.upload_media", return_value=None), \
             patch("bot.callbacks.recap.create_collage", return_value=None), \
             patch("bot.callbacks.recap.create_recap_story_image", return_value=None):
            await handle_callback_query(update, context)

        # Confirm copy_message was sent to PUBLIC_CHANNEL_ID
        context.bot.copy_message.assert_called_once_with(
            chat_id="-100111111",
            from_chat_id=9999,
            message_id=123
        )

        # Confirm send_message was NEVER called for PUBLIC_CHANNEL_ID (no second links message in event channel)
        for call in context.bot.send_message.call_args_list:
            self.assertNotEqual(str(call.kwargs.get("chat_id")), "-100111111")

        # Confirm bot.handlers last_recap_message_id is tracked for the discussion group forward
        import bot.state
        self.assertEqual(bot.state.runtime_state.last_recap_message_id, 777)
        self.assertEqual(bot.state.runtime_state.last_recap_events, test_events)

        # Simulate Telegram automatically forwarding the recap post into DISCUSSION_GROUP_ID
        fwd_update = MagicMock()
        fwd_msg = MagicMock()
        fwd_msg.chat_id = -100222222
        fwd_msg.message_id = 888
        fwd_msg.is_automatic_forward = True
        origin = MagicMock()
        origin.type = "channel"
        origin.message_id = 777
        fwd_msg.forward_origin = origin
        fwd_update.message = fwd_msg

        context.bot.send_message.reset_mock()
        await handle_discussion_forward(fwd_update, context)

        # Confirm send_message WAS called for the discussion chat group with the links text
        context.bot.send_message.assert_called_once()
        fwd_call = context.bot.send_message.call_args[1]
        self.assertEqual(fwd_call["chat_id"], -100222222)
        self.assertEqual(fwd_call["reply_to_message_id"], 888)
        self.assertIn("<b>Avventura D&amp;D</b>", fwd_call["text"])


class TestDeepLinkAndBookingKeyboard(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_deeplink.db")
        self.patch_db = patch("core.config.DB_PATH", self.db_path)
        self.patch_db.start()
        db.init_db()

        self.event_data = {
            "title": "One-Shot D&D <Special>",
            "date": "Venerdì 20-09-2026",
            "system": "D&D 5e",
            "seats": 4,
            "max_seats": 4,
            "booked_seats": 0,
            "description": "Una fantastica avventura",
        }
        self.event_id = db.insert_event(self.event_data, None, "raw text")
        db.update_event_status(self.event_id, "approved")

    def tearDown(self):
        self.patch_db.stop()
        self.temp_dir.cleanup()

    def test_booking_keyboard_without_bot_username(self):
        with patch("core.config.TELEGRAM_BOT_USERNAME", None):
            kb = get_event_booking_keyboard(self.event_id)
            self.assertEqual(len(kb.inline_keyboard), 1)
            row = kb.inline_keyboard[0]
            self.assertEqual(len(row), 2)
            self.assertEqual(row[0].text, "➕ Prenota")
            self.assertEqual(row[0].callback_data, f"book_{self.event_id}")
            self.assertEqual(row[1].text, "➖ Annulla")
            self.assertEqual(row[1].callback_data, f"unbook_{self.event_id}")

    def test_booking_keyboard_with_bot_username(self):
        kb = get_event_booking_keyboard(self.event_id, bot_username="GdG_Event_bot")
        self.assertEqual(len(kb.inline_keyboard), 1)
        row = kb.inline_keyboard[0]
        self.assertEqual(len(row), 3)
        self.assertEqual(row[0].text, "➕ Prenota")
        self.assertEqual(row[0].callback_data, f"book_{self.event_id}")
        self.assertEqual(row[1].text, "👥 Lista")
        self.assertEqual(row[1].url, f"https://t.me/GdG_Event_bot?start=subs_{self.event_id}")
        self.assertEqual(row[2].text, "➖ Annulla")
        self.assertEqual(row[2].callback_data, f"unbook_{self.event_id}")

    def test_booking_keyboard_with_at_prefix_bot_username(self):
        kb = get_event_booking_keyboard(self.event_id, bot_username="@GdG_Event_bot")
        row = kb.inline_keyboard[0]
        self.assertEqual(row[1].url, f"https://t.me/GdG_Event_bot?start=subs_{self.event_id}")

    def test_booking_keyboard_when_full(self):
        event = db.get_event(self.event_id)
        event["booked_seats"] = 4
        event["max_seats"] = 4

        kb = get_event_booking_keyboard(self.event_id, event=event, bot_username="GdG_Event_bot")
        row = kb.inline_keyboard[0]
        self.assertEqual(len(row), 3)
        self.assertEqual(row[0].text, "🚫 Esauriti")
        self.assertEqual(row[0].callback_data, f"full_{self.event_id}")
        self.assertEqual(row[1].text, "👥 Lista")
        self.assertEqual(row[2].text, "➖ Annulla")

    def test_format_event_participants_message_empty(self):
        event = db.get_event(self.event_id)
        msg = format_event_participants_message(event, [])
        self.assertIn("One-Shot D&amp;D &lt;Special&gt;", msg)
        self.assertIn("Posti occupati: <b>0/4</b>", msg)
        self.assertIn("Nessun partecipante iscritto al momento.", msg)

    def test_format_event_participants_message_with_reservations(self):
        event = db.get_event(self.event_id)
        reservations = [
            {"username": "mario", "user_id": 101, "seats_booked": 1},
            {"username": "@luigi<boss>", "user_id": 102, "seats_booked": 2},
            {"username": "", "user_id": 103, "seats_booked": 1},
        ]
        msg = format_event_participants_message(event, reservations)
        self.assertIn("<b>@mario</b>", msg)
        self.assertIn("<b>@luigi&lt;boss&gt;</b> (2 posti)", msg)
        self.assertIn("<b>ID:103</b>", msg)

    def test_format_event_participants_message_cancelled(self):
        event = db.get_event(self.event_id)
        event["status"] = "cancelled"
        msg = format_event_participants_message(event, [])
        self.assertIn("❌ <i>[ANNULLATO]</i>", msg)

    async def test_start_command_deep_link(self):
        db.book_seat(self.event_id, 1001, "player_one")
        update = MagicMock()
        update.message = AsyncMock()
        context = MagicMock()
        context.args = [f"subs_{self.event_id}"]

        await start_command(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        kwargs = update.message.reply_text.call_args[1]
        self.assertIn("Partecipanti all'evento", text)
        self.assertIn("One-Shot D&amp;D &lt;Special&gt;", text)
        self.assertIn("@player_one", text)
        self.assertEqual(kwargs.get("parse_mode"), "HTML")
        self.assertTrue(kwargs.get("disable_web_page_preview"))

    async def test_start_command_invalid_id(self):
        update = MagicMock()
        update.message = AsyncMock()
        context = MagicMock()
        context.args = ["subs_notanumber"]

        await start_command(update, context)

        update.message.reply_text.assert_called_once_with("❌ ID evento non valido.")

    async def test_start_command_nonexistent_event(self):
        update = MagicMock()
        update.message = AsyncMock()
        context = MagicMock()
        context.args = ["subs_999999"]

        await start_command(update, context)

        update.message.reply_text.assert_called_once_with("❌ Evento non trovato o già rimosso.")


class TestSubscribersWithoutUsername(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_subs_no_uname.db")
        self.db_patch = patch("core.config.DB_PATH", self.db_path)
        self.db_patch.start()
        db.init_db()

        self.event_id = db.insert_event({
            "title": "One-Shot Senza Username",
            "date": "2026-10-10",
            "normalized_date": "2026-10-10",
            "system": "D&D 5e",
            "host": "Master",
            "seats": "3/3",
            "max_seats": 3,
            "booked_seats": 0,
            "image_path": "dummy.jpg",
            "message_link": "https://t.me/c/123/789"
        }, "dummy.jpg", "raw")
        db.update_event_status(self.event_id, "approved")

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_format_reservation_subscriber_display(self):
        res1 = {"username": "steucestari", "user_id": 1609031146, "full_name": None}
        self.assertEqual(format_reservation_subscriber_display(res1, as_html=True), "@steucestari")
        self.assertEqual(format_reservation_subscriber_display(res1, as_html=False), "@steucestari")

        res2 = {"username": None, "user_id": 8893283822, "full_name": "Lorenzo Duarte"}
        self.assertEqual(
            format_reservation_subscriber_display(res2, as_html=True),
            '<a href="tg://user?id=8893283822">Lorenzo Duarte</a>'
        )
        self.assertEqual(
            format_reservation_subscriber_display(res2, as_html=False),
            "Lorenzo Duarte"
        )

        res3 = {"username": "Lorenzo Duarte", "user_id": 8893283822, "full_name": None}
        self.assertEqual(
            format_reservation_subscriber_display(res3, as_html=True),
            '<a href="tg://user?id=8893283822">Lorenzo Duarte</a>'
        )
        self.assertEqual(
            format_reservation_subscriber_display(res3, as_html=False),
            "Lorenzo Duarte"
        )

        res4 = {"username": "", "user_id": 99999, "full_name": None}
        self.assertEqual(format_reservation_subscriber_display(res4, as_html=True), "ID:99999")
        self.assertEqual(format_reservation_subscriber_display(res4, as_html=False), "ID:99999")

    def test_format_event_participants_message_no_at_for_non_username(self):
        event = db.get_event(self.event_id)
        reservations = [
            {"username": "steucestari", "user_id": 1609031146, "full_name": None, "seats_booked": 1},
            {"username": None, "user_id": 8893283822, "full_name": "Lorenzo Duarte", "seats_booked": 1},
            {"username": "ChicoMalo96", "user_id": 297895076, "full_name": None, "seats_booked": 1},
        ]
        msg = format_event_participants_message(event, reservations)

        self.assertIn("<b>@steucestari</b>", msg)
        self.assertIn("<b>@ChicoMalo96</b>", msg)
        self.assertNotIn("@Lorenzo", msg)
        self.assertIn('<b><a href="tg://user?id=8893283822">Lorenzo Duarte</a></b>', msg)

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

    def test_format_subscribers_management_view_no_at_for_non_username(self):
        event = db.get_event(self.event_id)
        reservations = [
            {"username": None, "user_id": 8893283822, "full_name": "Lorenzo Duarte", "seats_booked": 1},
        ]
        view = format_subscribers_management_view(event, reservations)
        self.assertNotIn("@Lorenzo", view)
        self.assertIn('<b><a href="tg://user?id=8893283822">Lorenzo Duarte</a></b> — 1 posto', view)

    def test_get_subscribers_management_keyboard_no_at_for_non_username(self):
        reservations = [
            {"id": 1, "username": None, "user_id": 8893283822, "full_name": "Lorenzo Duarte", "seats_booked": 1},
        ]
        kb = get_subscribers_management_keyboard(self.event_id, reservations)
        btn_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        for t in btn_texts:
            self.assertNotIn("@Lorenzo", t)
        self.assertTrue(any("Lorenzo Dua…" in t for t in btn_texts))

    async def test_handle_seat_booking_for_user_without_username(self):
        user = MagicMock()
        user.id = 8893283822
        user.username = None
        user.first_name = "Lorenzo"
        user.last_name = "Duarte"
        user.full_name = "Lorenzo Duarte"

        query = MagicMock()
        query.message.chat_id = -100123456
        query.message.message_id = 111
        query.answer = AsyncMock()

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        with patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("core.config.PUBLIC_CHANNEL_ID", "-1007890"), \
             patch("bot.service.booking.update_event_messages", AsyncMock()):
            await handle_seat_booking(self.event_id, user, query, context)

            res = db.get_reservation_by_user(self.event_id, user_id=8893283822)
            self.assertIsNotNone(res)
            self.assertIsNone(res["username"])
            self.assertEqual(res["full_name"], "Lorenzo Duarte")
            self.assertEqual(res["seats_booked"], 1)

            context.bot.send_message.assert_called()
            sent_text = context.bot.send_message.call_args[1]["text"]
            self.assertNotIn("@Lorenzo", sent_text)
            self.assertIn('<a href="tg://user?id=8893283822">Lorenzo Duarte</a>', sent_text)

            await handle_seat_unbooking(self.event_id, user, query, context)
            res_after = db.get_reservation_by_user(self.event_id, user_id=8893283822)
            self.assertIsNone(res_after)

    async def test_send_admin_action_notice_for_user_without_username(self):
        event = db.get_event(self.event_id)
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        admin_user = MagicMock()
        admin_user.username = "admin_user"
        admin_user.first_name = "Admin"

        with patch("core.config.DISCUSSION_GROUP_ID", "-100123456"):
            await send_admin_action_notice(
                context=context,
                event=event,
                target_username=None,
                target_full_name="Lorenzo Duarte",
                target_user_id=8893283822,
                action="add",
                seats=1,
                admin_user=admin_user,
            )
            context.bot.send_message.assert_called_once()
            text = context.bot.send_message.call_args[1]["text"]
            self.assertNotIn("@Lorenzo", text)
            self.assertIn('<a href="tg://user?id=8893283822">Lorenzo Duarte</a>', text)

    async def test_start_command_without_args(self):
        update = MagicMock()
        update.message = AsyncMock()
        context = MagicMock()
        context.args = []

        await start_command(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Gilda del Grifone", text)

    async def test_start_command_event_next_arg(self):
        update = MagicMock()
        update.effective_chat.id = 12345
        update.effective_chat.type = "private"
        update.message = AsyncMock()
        context = MagicMock()
        context.args = ["event_next"]

        with patch("bot.handlers.public.event_next_command", new_callable=AsyncMock) as mock_event_next:
            await start_command(update, context)
            mock_event_next.assert_called_once_with(update, context)



class TestUnpublishedEventSubscribers(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = self.test_db_path
        db.init_db()

        # Create an event that is still NOT published (status: pending)
        self.pending_event_id = db.insert_event({
            "title": "Unpublished Draft Event",
            "date": "Sabato 21:00",
            "normalized_date": "2026-10-10",
            "system": "Call of Cthulhu",
            "host": "Keeper",
            "seats": "4/4",
            "booked_seats": 0,
            "max_seats": 4,
            "description": "Una sessione non ancora pubblicata",
        }, None, "raw text")
        ev = db.get_event(self.pending_event_id)
        assert ev["status"] == "pending"

    def tearDown(self):
        config.DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()

    async def test_send_admin_action_notice_direct_unpublished_ignored(self):
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        admin_user = MagicMock(username="chief_admin", first_name="Chief")

        # 1. Pending event with no telegram_message_id
        ev = db.get_event(self.pending_event_id)
        with patch("core.config.DISCUSSION_GROUP_ID", "-100123456"):
            await send_admin_action_notice(
                context,
                ev,
                target_username="player1",
                action="add",
                seats=1,
                admin_user=admin_user,
            )
            context.bot.send_message.assert_not_called()

        # 2. Pending event even if telegram_message_id is set
        ev_with_msg_id = dict(ev)
        ev_with_msg_id["telegram_message_id"] = 998877
        with patch("core.config.DISCUSSION_GROUP_ID", "-100123456"):
            await send_admin_action_notice(
                context,
                ev_with_msg_id,
                target_username="player1",
                action="add",
                seats=1,
                admin_user=admin_user,
            )
            context.bot.send_message.assert_not_called()

        # 3. Discarded event
        ev_discarded = dict(ev)
        ev_discarded["status"] = "discarded"
        with patch("core.config.DISCUSSION_GROUP_ID", "-100123456"):
            await send_admin_action_notice(
                context,
                ev_discarded,
                target_username="player1",
                action="add",
                seats=1,
                admin_user=admin_user,
            )
            context.bot.send_message.assert_not_called()

    async def test_unpublished_event_sub_add_command_does_not_send_discussion_notice(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.effective_user.id = 111
        update.effective_user.username = "chief_admin"
        update.message.reply_to_message = None
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.args = [str(self.pending_event_id), "@player1", "2"]

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("bot.handlers.subscribers.update_event_messages", AsyncMock()):
            await event_sub_add_command(update, context)

            subs = db.get_reservations_for_event(self.pending_event_id)
            self.assertEqual(len(subs), 1)
            self.assertEqual(subs[0]["username"], "player1")
            self.assertEqual(subs[0]["seats_booked"], 2)

            update.message.reply_text.assert_called_once()
            self.assertIn("registrato con successo", update.message.reply_text.call_args[0][0])
            context.bot.send_message.assert_not_called()

    async def test_unpublished_event_sub_remove_command_does_not_send_discussion_notice(self):
        # Pre-register user
        db.admin_add_subscriber(self.pending_event_id, "@player1", seats=2)

        update = MagicMock()
        update.effective_chat.id = 999
        update.effective_user.id = 111
        update.effective_user.username = "chief_admin"
        update.message.reply_to_message = None
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        context.args = [str(self.pending_event_id), "@player1", "1"]

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("bot.handlers.subscribers.update_event_messages", AsyncMock()):
            await event_sub_remove_command(update, context)

            subs = db.get_reservations_for_event(self.pending_event_id)
            self.assertEqual(len(subs), 1)
            self.assertEqual(subs[0]["seats_booked"], 1)

            update.message.reply_text.assert_called_once()
            self.assertIn("Rimossi 1 posto/i", update.message.reply_text.call_args[0][0])
            context.bot.send_message.assert_not_called()

    async def test_unpublished_event_admin_reply_does_not_send_discussion_notice(self):
        update = MagicMock()
        update.effective_chat.id = 999
        update.effective_user.id = 111
        update.effective_user.username = "chief_admin"
        update.message.reply_text = AsyncMock()
        update.message.reply_to_message = MagicMock()
        update.message.reply_to_message.text = f"✏️ Invia l'username Telegram, rispondendo a questo messaggio, da aggiungere all'evento #{self.pending_event_id}"
        update.message.text = "@newplayer 1"
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        with patch("core.config.ADMIN_CHAT_ID", "999"), \
             patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("bot.handlers.subscribers.update_event_messages", AsyncMock()):
            await handle_admin_reply(update, context)

            subs = db.get_reservations_for_event(self.pending_event_id)
            self.assertEqual(len(subs), 1)
            self.assertEqual(subs[0]["username"], "newplayer")
            update.message.reply_text.assert_called_once()
            context.bot.send_message.assert_not_called()

    async def test_unpublished_event_sub_inc_and_dec_callbacks_do_not_send_discussion_notice(self):
        db.admin_add_subscriber(self.pending_event_id, "@player1", seats=1)
        subs = db.get_reservations_for_event(self.pending_event_id)
        res_id = subs[0]["id"]

        update = MagicMock()
        query = MagicMock()
        query.from_user.id = 111
        query.from_user.username = "chief_admin"
        query.message.chat_id = 999
        query.message.text = "👥 Gestione Iscritti"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update.callback_query = query
        context = MagicMock()
        context.bot.send_message = AsyncMock()

        with patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("core.config.DISCUSSION_GROUP_ID", "-100123456"), \
             patch("bot.callbacks.subscribers.update_event_messages", AsyncMock()):
            # sub_inc_
            query.data = f"sub_inc_{self.pending_event_id}_{res_id}"
            await handle_callback_query(update, context)

            subs_after = db.get_reservations_for_event(self.pending_event_id)
            self.assertEqual(subs_after[0]["seats_booked"], 2)
            context.bot.send_message.assert_not_called()

            # sub_dec_
            query.data = f"sub_dec_{self.pending_event_id}_{res_id}"
            await handle_callback_query(update, context)

            subs_after = db.get_reservations_for_event(self.pending_event_id)
            self.assertEqual(subs_after[0]["seats_booked"], 1)
            context.bot.send_message.assert_not_called()


class TestEventSubsCommand(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = os.path.join(self.temp_dir.name, "test_events.db")
        self.orig_db_path = config.DB_PATH
        config.DB_PATH = self.test_db_path
        db.init_db()

        self.event_id = db.insert_event({
            "title": "Trono di Spade",
            "date": "Venerdì 21:00",
            "max_seats": 6,
            "booked_seats": 2,
        }, None, "raw text")
        db.book_seat(self.event_id, 100, "player1", "Giocatore Uno")
        db.book_seat(self.event_id, 200, "player2", "Giocatore Due")

    def tearDown(self):
        config.DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()

    async def test_event_subs_command_with_arg(self):
        from bot.handlers.public import event_subs_command
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = [str(self.event_id)]

        await event_subs_command(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Trono di Spade", text)
        self.assertIn("@player1", text)
        self.assertIn("@player2", text)

    async def test_event_subs_command_with_regex_text(self):
        from bot.handlers.public import event_subs_command
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        update.message.text = f"/event_subs_{self.event_id}"
        context = MagicMock()
        context.args = []

        await event_subs_command(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Trono di Spade", text)

    async def test_event_subs_command_with_subs_alias_text(self):
        from bot.handlers.public import event_subs_command
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        update.message.text = f"/subs_{self.event_id}"
        context = MagicMock()
        context.args = []

        await event_subs_command(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Trono di Spade", text)

    async def test_event_subs_command_missing_arg(self):
        from bot.handlers.public import event_subs_command
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        update.message.text = "/event_subs"
        context = MagicMock()
        context.args = []

        await event_subs_command(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Specifica l'ID", text)

    async def test_event_subs_command_invalid_arg(self):
        from bot.handlers.public import event_subs_command
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = ["invalid_number"]

        await event_subs_command(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("ID evento non valido", text)

    async def test_event_subs_command_event_not_found(self):
        from bot.handlers.public import event_subs_command
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = ["999999"]

        await event_subs_command(update, context)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("non trovato", text)


if __name__ == "__main__":
    unittest.main()
