#!/usr/bin/env python3
"""
scripts/fix_event_keyboards.py

Utility script to fix/synchronize inline keyboards for events in the database.
By default, only approved events are updated.
Useful when event IDs have changed manually in SQLite and the existing buttons
on Telegram messages (public channel, discussion group, admin chat) still point
to outdated event IDs.

Usage:
    python3 scripts/fix_event_keyboards.py                 # Fix approved events only
    python3 scripts/fix_event_keyboards.py --status all   # Fix all events
    python3 scripts/fix_event_keyboards.py --event-id 12   # Fix single event
    python3 scripts/fix_event_keyboards.py --dry-run       # Simulate only
"""

import os
import sys
import argparse
import asyncio
import sqlite3
import logging
from typing import Optional

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from telegram import Bot
from telegram.request import HTTPXRequest
from telegram.error import RetryAfter, TimedOut, NetworkError, BadRequest, TelegramError

from core.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_BOT_USERNAME,
    PUBLIC_CHANNEL_ID,
    DISCUSSION_GROUP_ID,
    ADMIN_CHAT_ID,
    DB_PATH
)
from core.db import get_connection
from utils.date_utils import event_date_tuple
from bot.keyboards import (
    get_event_booking_keyboard,
    get_approval_keyboard,
    get_approved_event_keyboard,
    get_cancelled_event_keyboard
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("fix_event_keyboards")


async def execute_with_retry(coro_fn, max_retries: int = 5):
    """Executes a coroutine factory, retrying if Telegram rate limits (RetryAfter) or times out."""
    for attempt in range(max_retries + 1):
        try:
            return await coro_fn()
        except RetryAfter as e:
            wait_sec = (getattr(e, "retry_after", 3) or 3) + 1
            logger.warning(f"Flood control: sleeping {wait_sec}s (retry {attempt + 1}/{max_retries})...")
            await asyncio.sleep(wait_sec)
        except BadRequest:
            # Client errors (e.g. "Message is not modified", "Message to edit not found") must NOT be retried
            raise
        except (TimedOut, NetworkError) as e:
            if attempt < max_retries:
                logger.warning(f"Network / timeout ({e}): sleeping 3s (retry {attempt + 1}/{max_retries})...")
                await asyncio.sleep(3)
            else:
                raise
        except Exception as e:
            if "not modified" in str(e).lower():
                raise
            if attempt >= max_retries:
                raise
            logger.warning(f"API error ({e}): sleeping 2s (retry {attempt + 1}/{max_retries})...")
            await asyncio.sleep(2)


async def fix_keyboards(
    target_event_id: Optional[int] = None,
    since_id: Optional[int] = None,
    dry_run: bool = False,
    delay: float = 0.4,
    status: Optional[str] = "approved",
    upcoming_only: bool = True
):
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set in environment!")
        sys.exit(1)

    request = HTTPXRequest(connect_timeout=20.0, read_timeout=30.0)
    bot = Bot(token=TELEGRAM_BOT_TOKEN, request=request)

    try:
        bot_me = await bot.get_me()
        bot_username = bot_me.username or TELEGRAM_BOT_USERNAME
        clean_username = bot_username.lstrip("@") if bot_username else None
        logger.info(f"Connected to Telegram as @{bot_me.username} (ID: {bot_me.id})")
    except Exception as e:
        logger.error(f"Failed to authenticate with Telegram: {e}")
        sys.exit(1)

    # Fetch events from SQLite (only approved events by default)
    events = []
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            query = "SELECT * FROM events"
            params = []
            conditions = []

            if status:
                conditions.append("status = ?")
                params.append(status)
            else:
                conditions.append("status != 'discarded'")

            if target_event_id is not None:
                conditions.append("id = ?")
                params.append(target_event_id)
            elif since_id is not None:
                conditions.append("id >= ?")
                params.append(since_id)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY id ASC"

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            events = [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Failed to query database at {DB_PATH}: {e}")
        sys.exit(1)

    # Filter to only events from today onward if upcoming_only is True
    if upcoming_only and target_event_id is None:
        from datetime import datetime
        now_dt = datetime.now()
        today_tuple = (now_dt.year, now_dt.month, now_dt.day)
        upcoming_events = []
        for ev in events:
            dt = event_date_tuple(ev)
            if dt and dt >= today_tuple:
                upcoming_events.append(ev)
        events = upcoming_events

    if not events:
        if target_event_id:
            logger.warning(f"Event with ID {target_event_id} (status: {status or 'any'}) not found in database.")
        else:
            logger.warning(f"No events with status '{status or 'any'}' found to update.")
        return

    logger.info(f"Loaded {len(events)} event(s) to process (Filter: status={status or 'all'}). Dry-run: {dry_run}\n")

    stats = {
        "events_processed": 0,
        "channel_success": 0,
        "channel_skipped": 0,
        "channel_failed": 0,
        "discussion_success": 0,
        "discussion_skipped": 0,
        "discussion_failed": 0,
        "admin_success": 0,
        "admin_skipped": 0,
        "admin_failed": 0,
    }

    for ev in events:
        event_id = ev["id"]
        title = ev.get("title") or "Senza Titolo"
        status = ev.get("status") or "pending"
        tel_msg_id = ev.get("telegram_message_id")
        disc_msg_id = ev.get("discussion_message_id")
        disc_chat_id = ev.get("discussion_chat_id") or DISCUSSION_GROUP_ID
        admin_msg_id = ev.get("admin_message_id")

        logger.info(f"=== Event #{event_id}: '{title}' [Status: {status}] ===")
        stats["events_processed"] += 1

        # 1. Determine Public Booking Keyboard
        pub_keyboard = None
        if status == "approved":
            pub_keyboard = get_event_booking_keyboard(event_id, event=ev, bot_username=clean_username)

        # 2. Determine Admin Keyboard
        admin_keyboard = None
        if status == "pending":
            admin_keyboard = get_approval_keyboard(event_id)
        elif status == "approved":
            admin_keyboard = get_approved_event_keyboard(event_id)
        elif status == "cancelled":
            admin_keyboard = get_cancelled_event_keyboard(event_id)

        # Update Public Channel Message
        if PUBLIC_CHANNEL_ID and tel_msg_id:
            if dry_run:
                logger.info(f"  [DRY-RUN] Would update channel msg {tel_msg_id} in {PUBLIC_CHANNEL_ID}")
                stats["channel_success"] += 1
            else:
                try:
                    await execute_with_retry(lambda: bot.edit_message_reply_markup(
                        chat_id=PUBLIC_CHANNEL_ID,
                        message_id=int(tel_msg_id),
                        reply_markup=pub_keyboard
                    ))
                    logger.info(f"  ✅ Channel message {tel_msg_id} buttons updated.")
                    stats["channel_success"] += 1
                except Exception as e:
                    if "not modified" in str(e).lower():
                        logger.info(f"  ℹ️ Channel message {tel_msg_id} buttons already up to date.")
                        stats["channel_success"] += 1
                    else:
                        logger.warning(f"  ❌ Channel message {tel_msg_id} failed: {e}")
                        stats["channel_failed"] += 1
                if delay > 0:
                    await asyncio.sleep(delay)
        else:
            stats["channel_skipped"] += 1

        # Update Discussion Group Message
        if disc_chat_id and disc_msg_id:
            if dry_run:
                logger.info(f"  [DRY-RUN] Would update discussion msg {disc_msg_id} in {disc_chat_id}")
                stats["discussion_success"] += 1
            else:
                try:
                    await execute_with_retry(lambda: bot.edit_message_reply_markup(
                        chat_id=int(disc_chat_id),
                        message_id=int(disc_msg_id),
                        reply_markup=pub_keyboard
                    ))
                    logger.info(f"  ✅ Discussion message {disc_msg_id} buttons updated.")
                    stats["discussion_success"] += 1
                except Exception as e:
                    if "not modified" in str(e).lower():
                        logger.info(f"  ℹ️ Discussion message {disc_msg_id} buttons already up to date.")
                        stats["discussion_success"] += 1
                    else:
                        logger.warning(f"  ❌ Discussion message {disc_msg_id} failed: {e}")
                        stats["discussion_failed"] += 1
                if delay > 0:
                    await asyncio.sleep(delay)
        else:
            stats["discussion_skipped"] += 1

        # Update Admin Chat Message
        if ADMIN_CHAT_ID and admin_msg_id:
            if dry_run:
                logger.info(f"  [DRY-RUN] Would update admin msg {admin_msg_id} in {ADMIN_CHAT_ID}")
                stats["admin_success"] += 1
            else:
                try:
                    await execute_with_retry(lambda: bot.edit_message_reply_markup(
                        chat_id=int(ADMIN_CHAT_ID),
                        message_id=int(admin_msg_id),
                        reply_markup=admin_keyboard
                    ))
                    logger.info(f"  ✅ Admin message {admin_msg_id} buttons updated.")
                    stats["admin_success"] += 1
                except Exception as e:
                    if "not modified" in str(e).lower():
                        logger.info(f"  ℹ️ Admin message {admin_msg_id} buttons already up to date.")
                        stats["admin_success"] += 1
                    else:
                        logger.warning(f"  ❌ Admin message {admin_msg_id} failed: {e}")
                        stats["admin_failed"] += 1
                if delay > 0:
                    await asyncio.sleep(delay)
        else:
            stats["admin_skipped"] += 1

    # Print summary
    print("\n" + "=" * 55)
    print("           RIEPILOGO AGGIORNAMENTO BOTTONI")
    print("=" * 55)
    print(f"Eventi elaborati:            {stats['events_processed']}")
    print(f"Canale Pubblico ({PUBLIC_CHANNEL_ID}):")
    print(f"  - Aggiornati con successo: {stats['channel_success']}")
    print(f"  - Saltati (senza msg_id):  {stats['channel_skipped']}")
    print(f"  - Errori:                  {stats['channel_failed']}")
    print(f"Gruppo Discussione ({DISCUSSION_GROUP_ID}):")
    print(f"  - Aggiornati con successo: {stats['discussion_success']}")
    print(f"  - Saltati (senza msg_id):  {stats['discussion_skipped']}")
    print(f"  - Errori:                  {stats['discussion_failed']}")
    print(f"Gruppo Admin ({ADMIN_CHAT_ID}):")
    print(f"  - Aggiornati con successo: {stats['admin_success']}")
    print(f"  - Saltati (senza msg_id):  {stats['admin_skipped']}")
    print(f"  - Errori:                  {stats['admin_failed']}")
    print("=" * 55 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Fix inline keyboards on Telegram event messages to match database IDs.")
    parser.add_argument("--event-id", type=int, default=None, help="Fix only a specific event ID.")
    parser.add_argument("--since-id", type=int, default=None, help="Fix events with ID >= since_id.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without editing messages.")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between API calls in seconds (default: 0.3).")
    parser.add_argument("--status", type=str, default="approved", help="Filter by event status (default: approved). Pass 'all' to include all statuses.")
    parser.add_argument("--include-past", action="store_true", help="Include past events (default: only events from today onwards).")

    args = parser.parse_args()

    status_filter = None if args.status.lower() in ("all", "any") else args.status

    asyncio.run(fix_keyboards(
        target_event_id=args.event_id,
        since_id=args.since_id,
        dry_run=args.dry_run,
        delay=args.delay,
        status=status_filter,
        upcoming_only=not args.include_past
    ))


if __name__ == "__main__":
    main()

