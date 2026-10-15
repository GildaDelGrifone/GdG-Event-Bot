import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

import core.db as db
from bot.handlers.public import event_next_command, event_subs_command, start_command
from tests.support.config import patched_config
from tests.support.db import TempDBMixin, create_deep_link_event, create_event
from tests.support.telegram import make_context, make_update

ADMIN_CHAT = "-100999999"
DISCUSSION_GROUP = "-100888888"


class TestEventNextCommand(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def _event_next(self, chat_id, chat_type="group", **config_values):
        update = make_update(chat_id=chat_id, chat_type=chat_type)
        with patched_config(ADMIN_CHAT_ID=ADMIN_CHAT, **config_values):
            await event_next_command(update, make_context(bot_username="GdG_Event_bot"))
        return update.message.reply_text

    async def test_event_next_command_non_admin_ignored(self):
        reply_text = await self._event_next(12345)

        reply_text.assert_not_called()

    async def test_event_next_command_no_events(self):
        reply_text = await self._event_next(ADMIN_CHAT)

        reply_text.assert_called_once()
        self.assertIn("Nessun evento in programma", reply_text.call_args[0][0])

    async def test_event_next_command_lists_today_and_future_events(self):
        today_str = datetime.now().strftime("%d-%m-%Y")
        bare = dict(system=None, host=None, seats=None, booked_seats=None, max_seats=None, description=None)

        # 1. Past event (should NOT be included)
        create_event(status="approved", original_text="raw past", title="Evento Passato", date="01-01-2020",
                     normalized_date="01-01-2020", **bare)

        # 2. Today's event (SHOULD be included)
        ev_today_id = create_event(status="approved", original_text="raw today", title="Evento Di Oggi",
                                   date=f"Oggi {today_str} ore 21:00", normalized_date=today_str, **bare)
        db.update_event_field(ev_today_id, "admin_message_id", 301)
        db.update_discussion_message_info(ev_today_id, 401, DISCUSSION_GROUP)

        # 3. Future pending event (SHOULD be included)
        ev_future_id = create_event(original_text="raw future", title="Evento Futuro", date="Venerdì 25-12-2099",
                                    normalized_date="25-12-2099", **bare)
        db.update_event_field(ev_future_id, "admin_message_id", 302)

        reply_text = await self._event_next(ADMIN_CHAT, DISCUSSION_GROUP_ID=DISCUSSION_GROUP)

        reply_text.assert_called_once()
        text = reply_text.call_args[0][0]
        self.assertNotIn("Evento Passato", text)
        self.assertIn("Evento Di Oggi", text)
        self.assertIn("Evento Futuro", text)
        self.assertIn("[In attesa di approvazione]", text)
        self.assertIn('https://t.me/c/999999/301', text)
        self.assertIn('https://t.me/c/999999/302', text)
        self.assertIn('https://t.me/c/888888/401', text)
        self.assertIn('/event_subs &lt;id&gt;', text)
        self.assertNotIn(f'(/event_subs {ev_today_id})', text)
        self.assertIn('👥 Iscritti</a> (Nessun limite)', text)
        self.assertIn(f'start=subs_{ev_today_id}', text)

    async def test_event_next_command_public_private_chat_allowed(self):
        reply_text = await self._event_next(55555, "private", DISCUSSION_GROUP_ID=DISCUSSION_GROUP)

        reply_text.assert_called_once()
        self.assertIn("Nessun evento in programma", reply_text.call_args[0][0])

    async def test_event_next_command_discussion_group_allowed(self):
        reply_text = await self._event_next(DISCUSSION_GROUP, "supergroup", DISCUSSION_GROUP_ID=DISCUSSION_GROUP,
                                            ALLOW_GROUP_EVENT_NEXT=True)

        reply_text.assert_called_once()
        self.assertIn("Nessun evento in programma", reply_text.call_args[0][0])

    async def test_event_next_command_discussion_group_disabled(self):
        reply_text = await self._event_next(DISCUSSION_GROUP, "supergroup", DISCUSSION_GROUP_ID=DISCUSSION_GROUP,
                                            ALLOW_GROUP_EVENT_NEXT=False)

        reply_text.assert_not_called()


class TestStartCommand(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def _start(self, *args, update=None):
        update = update or make_update(chat_type="private")
        context = make_context(args=args)
        await start_command(update, context)
        return update.message.reply_text

    async def test_start_command_deep_link(self):
        event_id = create_deep_link_event()
        db.book_seat(event_id, 1001, "player_one")

        reply_text = await self._start(f"subs_{event_id}")

        reply_text.assert_called_once()
        text = reply_text.call_args[0][0]
        kwargs = reply_text.call_args[1]
        self.assertIn("Partecipanti all'evento", text)
        self.assertIn("One-Shot D&amp;D &lt;Special&gt;", text)
        self.assertIn("@player_one", text)
        self.assertEqual(kwargs.get("parse_mode"), "HTML")
        self.assertTrue(kwargs.get("disable_web_page_preview"))

    async def test_start_command_invalid_id(self):
        reply_text = await self._start("subs_notanumber")

        reply_text.assert_called_once_with("❌ ID evento non valido.")

    async def test_start_command_nonexistent_event(self):
        reply_text = await self._start("subs_999999")

        reply_text.assert_called_once_with("❌ Evento non trovato o già rimosso.")

    async def test_start_command_without_args(self):
        reply_text = await self._start()

        reply_text.assert_called_once()
        self.assertIn("Gilda del Grifone", reply_text.call_args[0][0])

    async def test_start_command_event_next_arg(self):
        update = make_update(chat_id=12345, chat_type="private")
        context = make_context(args=["event_next"])

        with patch("bot.handlers.public.event_next_command", new_callable=AsyncMock) as mock_event_next:
            await start_command(update, context)
            mock_event_next.assert_called_once_with(update, context)


class TestEventSubsCommand(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.event_id = db.insert_event({"title": "Trono di Spade", "date": "Venerdì 21:00", "max_seats": 6,
                                         "booked_seats": 2}, None, "raw text")
        db.book_seat(self.event_id, 100, "player1", "Giocatore Uno")
        db.book_seat(self.event_id, 200, "player2", "Giocatore Due")

    async def _subs(self, args=(), text=None):
        update = make_update(text=text)
        await event_subs_command(update, make_context(args=args))
        return update.message.reply_text

    async def test_event_subs_command_with_arg(self):
        reply_text = await self._subs([str(self.event_id)])

        reply_text.assert_called_once()
        text = reply_text.call_args[0][0]
        self.assertIn("Trono di Spade", text)
        self.assertIn("@player1", text)
        self.assertIn("@player2", text)

    async def test_event_subs_command_with_regex_text(self):
        reply_text = await self._subs(text=f"/event_subs_{self.event_id}")

        reply_text.assert_called_once()
        self.assertIn("Trono di Spade", reply_text.call_args[0][0])

    async def test_event_subs_command_with_subs_alias_text(self):
        reply_text = await self._subs(text=f"/subs_{self.event_id}")

        reply_text.assert_called_once()
        self.assertIn("Trono di Spade", reply_text.call_args[0][0])

    async def test_event_subs_command_missing_arg(self):
        reply_text = await self._subs(text="/event_subs")

        reply_text.assert_called_once()
        self.assertIn("Specifica l'ID", reply_text.call_args[0][0])

    async def test_event_subs_command_invalid_arg(self):
        reply_text = await self._subs(["invalid_number"])

        reply_text.assert_called_once()
        self.assertIn("ID evento non valido", reply_text.call_args[0][0])

    async def test_event_subs_command_event_not_found(self):
        reply_text = await self._subs(["999999"])

        reply_text.assert_called_once()
        self.assertIn("non trovato", reply_text.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
