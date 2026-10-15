import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import core.db as db
from bot.handlers.subscribers import event_sub_add_command, event_sub_remove_command, handle_admin_reply
from tests.support.config import as_admin_chat
from tests.support.db import TempDBMixin, create_subscribed_event, create_unpublished_event
from tests.support.telegram import admin_card, admin_update, make_context, make_message, make_user


def add_prompt(event_id):
    """The ForceReply prompt the bot sends after the "add subscriber" button."""
    return make_message(text=f"✏️ Invia l'username Telegram, rispondendo a questo messaggio, "
                             f"da aggiungere all'evento #{event_id}")


@contextmanager
def admin_chat_with_discussion():
    with as_admin_chat(DISCUSSION_GROUP_ID="-100123456"), \
         patch("bot.handlers.subscribers.update_event_messages", AsyncMock()):
        yield


def usernames(event_id):
    return [s["username"] for s in db.get_reservations_for_event(event_id)]


def seats_of(event_id, username):
    return next(s for s in db.get_reservations_for_event(event_id) if s["username"] == username)["seats_booked"]


class TestSubscriberCommands(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.event_id = create_subscribed_event()

    async def test_admin_commands(self):
        update = admin_update()
        reply_text = update.message.reply_text
        context = make_context(args=[str(self.event_id), "@peach", "2"])

        with admin_chat_with_discussion():
            await event_sub_add_command(update, context)
            reply_text.assert_called_once()
            self.assertIn("registrato con successo", reply_text.call_args[0][0])
            self.assertEqual(seats_of(self.event_id, "peach"), 2)

            reply_text.reset_mock()
            context.args = [str(self.event_id), "@peach", "1"]
            await event_sub_remove_command(update, context)
            reply_text.assert_called_once()
            self.assertIn("Rimossi 1 posto/i", reply_text.call_args[0][0])
            self.assertEqual(seats_of(self.event_id, "peach"), 1)

            update.message.reply_to_message = add_prompt(self.event_id)
            update.message.text = "@daisy 1"
            reply_text.reset_mock()
            await handle_admin_reply(update, context)
            reply_text.assert_called_once()
            self.assertIn("registrato con successo", reply_text.call_args[0][0])
            self.assertTrue(any(name == "daisy" for name in usernames(self.event_id)))

    async def test_admin_commands_reply_mode(self):
        update = admin_update(reply_to=admin_card(self.event_id, text=None, message_id=9999))
        reply_text = update.message.reply_text
        context = make_context(args=["@bowser", "1"])

        with admin_chat_with_discussion():
            await event_sub_add_command(update, context)
            reply_text.assert_called_once()
            self.assertIn("registrato con successo", reply_text.call_args[0][0])
            self.assertTrue(any(name == "bowser" for name in usernames(self.event_id)))

            # Remove via reply
            reply_text.reset_mock()
            context.args = ["@bowser"]
            await event_sub_remove_command(update, context)
            reply_text.assert_called_once()
            self.assertIn("Rimossi", reply_text.call_args[0][0])
            self.assertFalse(any(name == "bowser" for name in usernames(self.event_id)))

    async def test_admin_action_notice_on_admin_commands(self):
        update = admin_update(user=make_user(username="chief_admin"))
        context = make_context(args=[str(self.event_id), "@wario", "2"])
        send_message = context.bot.send_message

        with admin_chat_with_discussion():
            # /event_sub_add
            await event_sub_add_command(update, context)
            send_message.assert_called_once()
            call_kwargs = send_message.call_args[1]
            self.assertEqual(call_kwargs["chat_id"], -100123456)
            self.assertIn("admin degli eventi", call_kwargs["text"].lower())
            self.assertIn("@wario", call_kwargs["text"])
            self.assertIn("Aggiunti 2 posti", call_kwargs["text"])
            self.assertIn("@chief_admin", call_kwargs["text"])

            # /event_sub_remove
            send_message.reset_mock()
            context.args = [str(self.event_id), "@wario", "1"]
            await event_sub_remove_command(update, context)
            send_message.assert_called_once()
            call_kwargs = send_message.call_args[1]
            self.assertEqual(call_kwargs["chat_id"], -100123456)
            self.assertIn("admin degli eventi", call_kwargs["text"].lower())
            self.assertIn("@wario", call_kwargs["text"])
            self.assertIn("Rimosso 1 posto", call_kwargs["text"])

            # handle_admin_reply (ForceReply)
            send_message.reset_mock()
            update.message.reply_to_message = add_prompt(self.event_id)
            update.message.text = "@waluigi 1"
            await handle_admin_reply(update, context)
            send_message.assert_called_once()
            call_kwargs = send_message.call_args[1]
            self.assertEqual(call_kwargs["chat_id"], -100123456)
            self.assertIn("admin degli eventi", call_kwargs["text"].lower())
            self.assertIn("@waluigi", call_kwargs["text"])
            self.assertIn("Aggiunto 1 posto", call_kwargs["text"])


class TestUnpublishedEventSubscribers(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        # An event that is still NOT published (status: pending)
        self.pending_event_id = create_unpublished_event()
        self.assertEqual(db.get_event(self.pending_event_id)["status"], "pending")
        self.update = admin_update(user=make_user(111, "chief_admin"))

    async def test_unpublished_event_sub_add_command_does_not_send_discussion_notice(self):
        context = make_context(args=[str(self.pending_event_id), "@player1", "2"])

        with admin_chat_with_discussion():
            await event_sub_add_command(self.update, context)

            subs = db.get_reservations_for_event(self.pending_event_id)
            self.assertEqual(len(subs), 1)
            self.assertEqual(subs[0]["username"], "player1")
            self.assertEqual(subs[0]["seats_booked"], 2)

            self.update.message.reply_text.assert_called_once()
            self.assertIn("registrato con successo", self.update.message.reply_text.call_args[0][0])
            context.bot.send_message.assert_not_called()

    async def test_unpublished_event_sub_remove_command_does_not_send_discussion_notice(self):
        db.admin_add_subscriber(self.pending_event_id, "@player1", seats=2)
        context = make_context(args=[str(self.pending_event_id), "@player1", "1"])

        with admin_chat_with_discussion():
            await event_sub_remove_command(self.update, context)

            subs = db.get_reservations_for_event(self.pending_event_id)
            self.assertEqual(len(subs), 1)
            self.assertEqual(subs[0]["seats_booked"], 1)

            self.update.message.reply_text.assert_called_once()
            self.assertIn("Rimossi 1 posto/i", self.update.message.reply_text.call_args[0][0])
            context.bot.send_message.assert_not_called()

    async def test_unpublished_event_admin_reply_does_not_send_discussion_notice(self):
        self.update.message.reply_to_message = add_prompt(self.pending_event_id)
        self.update.message.text = "@newplayer 1"
        context = make_context()

        with admin_chat_with_discussion():
            await handle_admin_reply(self.update, context)

            subs = db.get_reservations_for_event(self.pending_event_id)
            self.assertEqual(len(subs), 1)
            self.assertEqual(subs[0]["username"], "newplayer")
            self.update.message.reply_text.assert_called_once()
            context.bot.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
