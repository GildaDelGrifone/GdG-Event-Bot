import unittest
from datetime import datetime
from unittest.mock import patch

from telegram.error import TelegramError

import core.db as db
from bot.service.open_seats import (
    build_open_seats_messages, open_seat_events, scheduled_open_seats_reminder, send_open_seats_after_recap,
    send_open_seats_reminder,
)
from bot.state import runtime_state
from tests.support.config import patched_config
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import make_bot

NOW = datetime(2026, 11, 10, 16, 0)  # a Tuesday
LINK = "https://t.me/canale/{}"


def channel_event(title, day, status="approved", link=True, **fields):
    """An event dated `day` (dd-mm-yyyy); approved events get a channel link unless link=False."""
    event_id = create_event(status=status, title=title, date=f"{day} 21:00", normalized_date=day,
                            message_link=LINK.format(title) if link else None, **fields)
    return event_id


class TestOpenSeatEvents(TempDBMixin, unittest.TestCase):
    def test_only_future_approved_posted_events_with_free_seats(self):
        channel_event("Domani", "11-11-2026", max_seats=5, seats="5/5", booked_seats=2)
        channel_event("Illimitato", "13-11-2026", max_seats=None, seats="no limit", booked_seats=7)
        channel_event("Oggi", "10-11-2026", max_seats=5, seats="5/5")
        channel_event("Passato", "08-11-2026", max_seats=5, seats="5/5")
        channel_event("In attesa", "11-11-2026", status="pending", max_seats=5, seats="5/5")
        channel_event("Annullato", "11-11-2026", status="cancelled", max_seats=5, seats="5/5")
        channel_event("Pieno", "11-11-2026", max_seats=3, seats="0/3 Completo", booked_seats=3)
        channel_event("Tavolo privato", "11-11-2026", max_seats=0, seats="0/0 Completo")
        channel_event("Solo Eventbrite", "11-11-2026", link=False, max_seats=5, seats="5/5")
        create_event(status="approved", title="Senza data", date="presto", normalized_date="",
                     message_link=LINK.format("x"), max_seats=5, seats="5/5")

        titles = [ev["title"] for ev in open_seat_events(NOW)]
        self.assertEqual(titles, ["Domani", "Illimitato"])

    def test_a_seat_freed_by_an_unbooking_brings_the_event_back(self):
        event_id = channel_event("Pieno", "11-11-2026", max_seats=1, seats="1/1")
        db.book_seat(event_id, 1, username="anna")
        self.assertEqual(open_seat_events(NOW), [])
        db.unbook_seat(event_id, 1, username="anna")
        self.assertEqual([ev["id"] for ev in open_seat_events(NOW)], [event_id])


class TestBuildMessages(TempDBMixin, unittest.TestCase):
    def test_events_of_the_same_day_share_one_header(self):
        channel_event("Venerdì A", "13-11-2026", max_seats=4, seats="4/4", booked_seats=3, system="D&D 5e")
        channel_event("Mercoledì A", "11-11-2026", max_seats=5, seats="5/5", booked_seats=3, system="CoC 7a Ed.")
        channel_event("Mercoledì B", "11-11-2026", max_seats=None, seats="no limit", system="")

        [text] = build_open_seats_messages(open_seat_events(NOW))

        self.assertTrue(text.startswith("🎲 <b>Posti ancora disponibili</b>\n\n"))
        self.assertEqual(text.count("📅"), 2)
        self.assertLess(text.index("Mercoledì 11-11"), text.index("Venerdì 13-11"))
        self.assertIn(f'• <a href="{LINK.format("Mercoledì A")}"><b>Mercoledì A</b></a> (CoC 7a Ed.) — 2/5', text)
        self.assertIn(f'• <a href="{LINK.format("Mercoledì B")}"><b>Mercoledì B</b></a> — no limit', text)
        self.assertIn("(D&amp;D 5e) — 1/4", text)
        for absent in ("Iscritti", "event_subs", "Admin", "Chat Discussione", "Per visualizzare"):
            self.assertNotIn(absent, text)

    def test_a_long_list_is_split_between_days(self):
        for day in range(11, 31):
            for n in range(4):
                channel_event(f"Evento con un titolo piuttosto lungo {day}-{n}", f"{day:02d}-11-2026",
                              max_seats=5, seats="5/5", system="Un sistema di gioco qualsiasi")

        messages = build_open_seats_messages(open_seat_events(NOW))

        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(text) <= 3800 for text in messages))
        self.assertTrue(messages[0].startswith("🎲"))
        self.assertTrue(all(text.startswith("📅") for text in messages[1:]))
        self.assertEqual(sum(text.count("📅") for text in messages), 20)

    def test_no_events_no_messages(self):
        self.assertEqual(build_open_seats_messages([]), [])


class ResetSentDay:
    """Forgets the day the reminder was last posted, before and after each test."""

    def setUp(self):
        super().setUp()
        sent_patch = patch.object(runtime_state, "open_seats_sent_on", None)
        sent_patch.start()
        self.addCleanup(sent_patch.stop)


class TestSendOpenSeatsReminder(ResetSentDay, TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_posts_in_the_discussion_group(self):
        channel_event("Domani", "11-11-2026", max_seats=5, seats="5/5")
        bot = make_bot()
        with patched_config(DISCUSSION_GROUP_ID="-100777"):
            self.assertEqual(await send_open_seats_reminder(bot, now=NOW), 1)
        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.call_args.kwargs
        self.assertEqual(kwargs["chat_id"], "-100777")
        self.assertEqual(kwargs["parse_mode"], "HTML")
        self.assertTrue(kwargs["disable_web_page_preview"])
        self.assertIn("Domani", kwargs["text"])

    async def test_nothing_is_sent_without_events(self):
        channel_event("Oggi", "10-11-2026", max_seats=5, seats="5/5")
        bot = make_bot()
        with patched_config(DISCUSSION_GROUP_ID="-100777"):
            self.assertEqual(await send_open_seats_reminder(bot, now=NOW), 0)
        bot.send_message.assert_not_called()

    async def test_nothing_is_sent_without_a_discussion_group(self):
        channel_event("Domani", "11-11-2026", max_seats=5, seats="5/5")
        bot = make_bot()
        with patched_config(DISCUSSION_GROUP_ID=None):
            self.assertEqual(await send_open_seats_reminder(bot, now=NOW), 0)
        bot.send_message.assert_not_called()

    async def test_a_telegram_error_is_logged_not_raised(self):
        channel_event("Domani", "11-11-2026", max_seats=5, seats="5/5")
        bot = make_bot()
        bot.send_message.side_effect = TelegramError("chat not found")
        with patched_config(DISCUSSION_GROUP_ID="-100777"), \
             patch("bot.common.messages.logger"), self.assertLogs("bot.service.open_seats", "WARNING"):
            self.assertEqual(await send_open_seats_reminder(bot, now=NOW), 0)


RECAP_DAY = datetime(2026, 11, 11, 16, 0)  # a Wednesday, a recap weekday by default
QUIET_DAY = datetime(2026, 11, 10, 16, 0)  # a Tuesday, no recap


class TestScheduling(ResetSentDay, TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        channel_event("Venerdì", "13-11-2026", max_seats=5, seats="5/5")
        self.bot = make_bot()
        config_patch = patched_config(DISCUSSION_GROUP_ID="-100777", RECAP_WEEKDAYS=[0, 2, 4, 5, 6],
                                      OPEN_SEATS_REMINDER_ENABLED=True)
        config_patch.__enter__()
        self.addCleanup(config_patch.__exit__, None, None, None)

    async def test_the_job_posts_on_a_day_without_recap(self):
        self.assertEqual(await scheduled_open_seats_reminder(self.bot, now=QUIET_DAY), 1)
        self.assertEqual(runtime_state.open_seats_sent_on, "10-11-2026")

    async def test_the_job_posts_on_a_recap_weekday_with_no_event_tonight(self):
        self.assertEqual(await scheduled_open_seats_reminder(self.bot, now=RECAP_DAY), 1)

    async def test_the_job_leaves_it_to_the_recap_when_there_are_events_tonight(self):
        channel_event("Stasera", "11-11-2026", max_seats=5, seats="5/5")
        self.assertEqual(await scheduled_open_seats_reminder(self.bot, now=RECAP_DAY), 0)
        self.bot.send_message.assert_not_called()

        self.assertEqual(await send_open_seats_after_recap(self.bot, now=RECAP_DAY), 1)
        self.assertNotIn("Stasera", self.bot.send_message.call_args.kwargs["text"])

    async def test_posted_at_most_once_a_day(self):
        await scheduled_open_seats_reminder(self.bot, now=QUIET_DAY)
        self.assertEqual(await send_open_seats_after_recap(self.bot, now=QUIET_DAY), 0)
        self.assertEqual(await scheduled_open_seats_reminder(self.bot, now=QUIET_DAY), 0)
        self.assertEqual(self.bot.send_message.await_count, 1)
        # The next day it goes out again
        self.assertEqual(await scheduled_open_seats_reminder(self.bot, now=datetime(2026, 11, 12, 16, 0)), 1)

    async def test_nothing_after_the_recap_when_disabled(self):
        with patched_config(OPEN_SEATS_REMINDER_ENABLED=False):
            self.assertEqual(await send_open_seats_after_recap(self.bot, now=RECAP_DAY), 0)
        self.bot.send_message.assert_not_called()

    async def test_a_failed_post_is_not_remembered(self):
        self.bot.send_message.side_effect = TelegramError("chat not found")
        with patch("bot.common.messages.logger"), self.assertLogs("bot.service.open_seats", "WARNING"):
            await scheduled_open_seats_reminder(self.bot, now=QUIET_DAY)
        self.assertIsNone(runtime_state.open_seats_sent_on)


if __name__ == "__main__":
    unittest.main()
