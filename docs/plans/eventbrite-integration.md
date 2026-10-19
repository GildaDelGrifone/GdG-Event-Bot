# Eventbrite Integration Plan (GdG-Event-Bot)

## Context
Today events are booked only through Telegram (`➕ Prenota` / `➖ Annulla`). Admins also want to publish an event on **Eventbrite**, so people outside Telegram can book a seat there. One seat pool is shared by both platforms:
- A booking on either side updates the other side's availability.
- Eventbrite bookings are announced in the discussion group, and an `.env` flag can turn those announcements off.
- Edits and cancellations made in Telegram are mirrored on Eventbrite.

**Decisions already taken with the user:**
- **Sync:** polling with an APScheduler job. No webhooks and no web server.
- **Publish UX:** the pending card gets `[🚀 Publish + Eventbrite]`. An approved card gets `[🎟️ Pubblica su Eventbrite]` so an event can be pushed later.
- **Unlimited events:** they use `EVENTBRITE_UNLIMITED_CAPACITY` (default 50) on Eventbrite. Telegram stays unlimited.
- **Tickets per order:** no per-order cap of our own. Eventbrite's default applies, bounded by the remaining capacity.
- **Cancellation, Eventbrite event with no orders:** unpublish it. This can be undone, so `♻️ Riattiva` can republish.
- **Cancellation, Eventbrite event with orders:**
  1. Close sales by setting the ticket quantity to the number sold.
  2. Rename the event to `[ANNULLATO] …`.
  3. **Try the cancel API**.
  4. If Eventbrite refuses, send the admins the Eventbrite dashboard link so they can do the one-click cancel. Eventbrite then emails the attendees.
  5. The poller confirms the cancellation once it happens.
- **Attendee names:** shown as first name plus initial (`Mario R.`). Emails are **never stored**.
- **Eventbrite link:** only in the discussion-group booking message (`👇 Gestisci qui la tua prenotazione!` plus a link line). The channel post is unchanged.
- **Eventbrite bookings in 👥 Gestisci Iscritti:** no ± buttons. Each Eventbrite row is a **URL button** that opens the event's Eventbrite dashboard. The DB layer also refuses admin ± on those rows.

**Eventbrite API facts the design relies on.** Base URL is `https://www.eventbriteapi.com/v3`, with `Authorization: Bearer <token>`.
- **Create:** `POST /organizations/{org}/events/` takes `name.html`, `start`/`end` as `{timezone, utc:"YYYY-MM-DDThh:mm:ssZ"}`, `currency`, `venue_id`, `listed`, `logo_id`. The start must be in the future.
- **Description:** `event.description` is deprecated. Use `summary` (≤140 characters) and `POST /events/{id}/structured_content/{version}/` with `{"modules":[{"type":"text","data":{"body":{"type":"text","text":"<p>..</p>","alignment":"left"}}}],"publish":true,"purpose":"listing"}`.
  - The version starts at 1 and each write must send the last version + 1.
  - Every write must resend all modules.
- **Ticket class:** `POST /events/{id}/ticket_classes/` with `{"ticket_class":{"name":"Posto","free":true,"quantity_total":N}}`. Update it with `POST /events/{id}/ticket_classes/{tc}/`.
- **Status changes:**
  - `POST /events/{id}/publish/` publishes.
  - `/unpublish/` and `/cancel/` both work **only with no orders**. A cancelled event cannot be revived.
  - Status values are `draft|live|started|ended|completed|canceled`.
- **Logo (three steps):**
  1. `GET /media/upload/?type=image-event-logo` returns `upload_url`, `upload_data`, `file_parameter_name` and `upload_token`.
  2. Send a multipart POST to `upload_url` with no auth header.
  3. `POST /media/upload/` with `{upload_token, crop_mask:{top_left:{x:0,y:0},width,height}}` returns the media `id`. The crop must be **2:1**.
- **Orders:** `GET /events/{id}/orders/?status=all_not_deleted&expand=attendees`.
  - Pagination: `pagination.has_more_items` plus the `continuation` token.
  - Each attendee has `id, order_id, cancelled, refunded, profile.first_name/last_name/name`.
- **Read-after-write:** Eventbrite is eventually consistent, so **trust POST response bodies** instead of reading back right after a write.
- **Rate limits:** 2000 calls per hour per token. Event creation and publishing are limited to 200 per hour each.
- **Unverified (test against a real event, see Verification):**
  - Whether lowering `quantity_total` below the sold count returns 400. We always clamp, so it shouldn't matter.
  - Whether changing the date works once orders exist.
  - How an attendee's own cancellation shows up (`cancelled`/`refunded` flags). We filter on both.
  - The exact dashboard URL formats.
  - The maximum length of the event name.

---

## Architecture overview
```
Telegram action ──► core.db (seats/reservations) ──► bot.service.posts.update_event_messages
                                                         ├─ channel post + discussion reply (existing)
                                                         └─ bot.service.eventbrite.sync_eventbrite  (NEW: capacity/content/logo push)
APScheduler every N min ──► bot.service.eventbrite_poll.poll_eventbrite_bookings
                              └─ core.eventbrite (HTTP) → diff orders vs reservations(source='eventbrite')
                                 → core.db.seats.apply_eventbrite_order → update_event_messages → discussion notice
```
`update_event_messages` (`bot/service/posts.py`) runs after **every** booking, unbooking, admin seat change and edit. That makes it the single hook point for pushing capacity and content to Eventbrite.

Seat model:
- `eb_seats` is the sum of `seats_booked` over the event's reservation rows with `source='eventbrite'`.
- `telegram_booked` is `booked_seats - eb_seats`.
- `capacity` is `max_seats`, or `EVENTBRITE_UNLIMITED_CAPACITY` when `max_seats` is NULL.
- **The ticket class quantity is `quantity_total = max(eb_seats, capacity - telegram_booked)`.** On Eventbrite, quantity minus sold then equals the seats still free in Telegram.
- When the event is cancelled, `quantity_total = eb_seats`, which closes sales.

---

## Implementation steps (do them in order; write the tests for each step before moving on)

### 1. Configuration — `core/config.py`, `.env.example`
Add the following, read at call time like the existing settings and using `_env_bool` for the booleans:
```
EVENTBRITE_TOKEN              # private OAuth token
EVENTBRITE_ORGANIZATION_ID
EVENTBRITE_VENUE_ID           # created once via scripts/eventbrite_setup.py
EVENTBRITE_ORGANIZER_ID       # optional; sent as organizer_id when set
EVENTBRITE_TIMEZONE=Europe/Rome
EVENTBRITE_CURRENCY=EUR
EVENTBRITE_LISTED=true        # false = unlisted (useful for testing)
EVENTBRITE_DEFAULT_START_TIME=20:45   # used when the event date string has no time
EVENTBRITE_EVENT_DURATION_HOURS=4
EVENTBRITE_UNLIMITED_CAPACITY=50
EVENTBRITE_POLL_MINUTES=2
EVENTBRITE_BOOKING_NOTIFICATIONS=true # discussion-group notice for EB bookings/releases
```
Add `eventbrite_enabled()` to `core/eventbrite/client.py`, returning True when the token, organization ID and venue ID are all set. Every button and hook checks it, so the bot behaves exactly as today when Eventbrite isn't configured.

### 2. Database — `core/db/schema.py`, `core/db/events.py`, `core/db/seats.py`, `core/db/reservations.py`
- **Schema.** Add these columns to the `CREATE TABLE` statements **and** to `COLUMN_MIGRATIONS`:
  - `events`:
    - `eventbrite_event_id TEXT`, `eventbrite_url TEXT`, `eventbrite_ticket_class_id TEXT`.
    - `eventbrite_status TEXT`: our view of the state, one of `draft|live|unpublished|closed|canceled`. `closed` means we cancelled in Telegram, the event has orders and Eventbrite has not cancelled it yet.
    - `eventbrite_quantity_total INTEGER`: the last quantity we pushed, cached to skip no-op calls.
    - `eventbrite_content_version INTEGER DEFAULT 0`: the structured-content page version.
    - `eventbrite_synced_at TEXT`.
  - `reservations`: `source TEXT DEFAULT 'telegram'` and `eventbrite_order_id TEXT`.
  - Add an `INDEXES` tuple applied in `init_db()`: `CREATE UNIQUE INDEX IF NOT EXISTS idx_res_eb_order ON reservations(event_id, eventbrite_order_id) WHERE eventbrite_order_id IS NOT NULL`.
- **`core/db/events.py`:**
  - `set_eventbrite_info(event_id, **fields)`: a whitelisted update of the `eventbrite_*` columns only. Keep them out of `EDITABLE_EVENT_FIELDS` so admins can't set them through `/event_edit_*`.
  - `clear_eventbrite_info(event_id)`: used before re-creating an event that Eventbrite cancelled.
  - `get_eventbrite_tracked_events()`: rows with `eventbrite_event_id IS NOT NULL` and status `approved` or `cancelled` whose date (via `event_date_tuple`) is today or later, or yesterday, so late cancellations are still seen.
- **`core/db/reservations.py`:** `get_eventbrite_reservations(event_id)` and `eventbrite_seat_count(event_id)`.
- **`core/db/seats.py`:**
  - Add `apply_eventbrite_order(event_id, order_id, display_name, seats)` in one `transaction()`, reusing `_load_seat_state(..., cancelled_message=None)` and `_set_booked_seats`:
    - Upsert or delete the reservation row (`source='eventbrite'`, `user_id=NULL`, `username=NULL`, `full_name=display_name`).
    - Adjust `booked_seats` by the delta, **with no capacity check**: the booking has already happened on Eventbrite.
    - Return `(old_seats, new_seats, overbooked)`, where `overbooked` means `booked > max_seats`.
  - Harden the existing functions:
    - `admin_add_seat` and `admin_remove_seat` return `(False, "Prenotazione Eventbrite: gestiscila dalla dashboard Eventbrite.")` when `res['source'] == 'eventbrite'`.
    - `unbook_seat`, `admin_remove_subscriber` and the `book_seat` claim query add `AND COALESCE(source,'telegram') != 'eventbrite'`. A Telegram user named "Mario R." must never match an Eventbrite row.
- Export the new functions from `core/db/__init__.py` (`__all__`).

### 3. Eventbrite HTTP client — new package `core/eventbrite/`
Mirror `core/wordpress/`: a facade `__init__.py` with `__all__`, synchronous `requests` calls and a 30-second timeout. Callers wrap calls in `asyncio.to_thread`, the way `core/instagram.py` is used.
- **`client.py`:**
  - `API_BASE` and `eventbrite_enabled()`.
  - `eb_get(path, params=None)` and `eb_post(path, json=None)`, which add the Bearer header.
  - `EventbriteError(status_code, error, description)`, parsed from the JSON body's `error` constant. Branch on `.error`, never on the description text.
  - `paginate(path, params, key)`, which follows `continuation` while `has_more_items` is true.
- **`payload.py`:** pure functions with no HTTP; unit-test these heavily.
  - `event_start_end(event) -> (start_dt_utc, end_dt_utc)`, which uses `utils.date_utils.extract_event_datetime` (step 9), `zoneinfo.ZoneInfo(config.EVENTBRITE_TIMEZONE)` and the configured duration. Raise `ValueError("data nel passato")` or `ValueError("data mancante")` when there's no usable future start.
  - `event_payload(event)`: `name.html` is the HTML-escaped title, prefixed with `[ANNULLATO] ` when cancelled and truncated to 75 characters. `summary` (≤140 characters) comes from the description or the system. Also sets `start`, `end`, `currency`, `venue_id`, `listed`, `organizer_id` (if set), `shareable: true`, `show_remaining: true`.
  - `description_modules(event)`: one text module whose HTML uses only `p, b, em, ul, li, a`. It holds:
    - Sistema, Master/Host (the label follows `is_roleplay`), Dettagli (`extra_info`, newlines become `<br>`) and the description.
    - A footer with the address (`Gilda del Grifone, Via Ada Negri 8/A, Torino`), placed in a module constant next to the one in `utils/templates.py`.
    - A link to the Telegram post when `message_link` is set.
  - `ticket_quantity(event, eb_seats, unlimited_capacity)`: the seat-model formula above.
  - `attendee_display_name(profile)`: `"Mario R."`, falling back to `profile.name`, then `"Partecipante Eventbrite"`.
  - `dashboard_url(eb_event_id)` → `https://www.eventbrite.com/myevent?eid={id}`, and `attendees_dashboard_url(eb_event_id)` → `https://www.eventbrite.com/attendees-manage?eid={id}`. Confirm both formats manually.
- **`events.py`:**
  - `create_event(payload)` returns the event JSON, including `id` and `url`.
  - `update_event(eb_id, payload)`, `publish_event`, `unpublish_event` and `cancel_event`; the last three return a bool and raise `EventbriteError` on refusal.
  - `get_event(eb_id)`, which uses `expand=ticket_classes` to read `status` and `quantity_sold`.
  - `set_description(eb_id, modules, version)` returns the new version number.
- **`tickets.py`:** `create_free_ticket_class(eb_id, quantity, sales_end_utc)`, where sales end at the event's end time, and `update_ticket_quantity(eb_id, tc_id, quantity)`.
- **`media.py`:** `upload_logo(image_path)` implements the three-step flow. It first calls a new helper, `utils/image_utils.pad_to_aspect(path, ratio=2.0, min_size=(2160,1080))`, which centres the image on a blurred, enlarged copy of itself and writes a temporary JPEG with Pillow (already a dependency). It returns the media id.
- **`orders.py`:** `fetch_active_orders(eb_id) -> {order_id: (display_name, seat_count)}`. It counts attendees where `not cancelled and not refunded`, and skips orders that end up with 0 seats.

### 4. Telegram-side Eventbrite service — new `bot/service/eventbrite.py`
- **`publish_event_to_eventbrite(context, event_id, admin_chat_id)`:**
  1. Check: the integration is enabled, the event is `approved`, and `event_start_end` raises nothing. On failure send `❌ Eventbrite: <motivo>` to the admin chat and return.
     - **A full event (`max_seats` is not NULL and `ticket_quantity(...) - eb_seats <= 0`, e.g. a `0/0 Completo` post or `2/2` already booked on Telegram) is refused.** Send `❌ Eventbrite: l'evento non ha posti liberi (X/Y), non c'è nulla da prenotare su Eventbrite. Aggiorna i posti con /event_edit_seats e riprova con [🎟️ Pubblica su Eventbrite].` Nothing is created on Eventbrite, so no empty sold-out event is left behind, and a ticket class with `quantity_total` 0 is never attempted. The buttons stay visible, so the admin can retry after freeing seats.
     - `max_seats` NULL (unlimited, e.g. after `/event_edit_seats 0` or `null`) is **not** "full"; it uses `EVENTBRITE_UNLIMITED_CAPACITY`. Keep the check on `max_seats == 0` separate from the NULL check, because `parse_seats_input` treats a bare `0` as unlimited while the AI parser stores `0/0 Completo` as `max_seats = 0`.
     - With `[🚀 Publish + Eventbrite]`, the Telegram publish still happens; only the Eventbrite step is refused, with the message above.
     - An event that becomes full **after** being published on Eventbrite is not affected by this check: `ticket_quantity` clamps to `eb_seats`, so Eventbrite simply shows it as sold out, and it reopens when a seat frees up.
  2. Make it **idempotent**. If `eventbrite_event_id` exists and the status is `draft`, resume from the failed step. If it is already live, reply with the existing link.
  3. Inside `asyncio.to_thread`, run the steps in order, storing ids after each one via `set_eventbrite_info`: create the event, create the ticket class (quantity from `ticket_quantity`), upload the logo (only if `image_path` exists; a logo failure is a warning, not fatal), set the description at version 1, then publish. Store `eventbrite_status='live'`, the `url` from the create response, and `eventbrite_quantity_total`.
  4. Send the admins `✅ Evento pubblicato su Eventbrite: <url>`. Refresh the admin card keyboard (`get_approved_event_keyboard(event_id, event)`) and call `update_event_messages`, so the discussion reply gains the link.
- **`sync_eventbrite(context, event, content_changed=False, image_changed=False)`:** returns immediately when Eventbrite is disabled, when there's no `eventbrite_event_id`, or when `eventbrite_status` is `canceled` or `draft`.
  - **Capacity:** only when the event status is `approved`. If `ticket_quantity(...)` differs from `eventbrite_quantity_total`, call `update_ticket_quantity` and cache the new value.
  - `content_changed` triggers `update_event` (name, summary, start/end) and `set_description(version + 1)`.
  - `image_changed` triggers `upload_logo` and then `update_event(logo_id)`.
  - Errors are logged and sent to the admin chat as `⚠️ Sync Eventbrite fallita per #id: …`. They must never raise into the Telegram flow.
  - If `event_start_end` raises because a date edit moved the event into the past, skip the date fields and warn the admins.
- **`cancel_on_eventbrite(context, event)`:**
  - With no Eventbrite orders (from `fetch_active_orders`; the DB count may lag), call `unpublish_event` and set the status to `unpublished`. If unpublishing fails, fall through to the branch below.
  - With orders:
    1. Set the ticket quantity to `eb_seats`.
    2. Call `update_event` with the `[ANNULLATO]` name.
    3. **Try `cancel_event`.** On success set the status to `canceled` and send the admins `✅ annullato anche su Eventbrite`.
    4. Otherwise set the status to `closed` and send the admins: `⚠️ L'evento ha N prenotazioni Eventbrite: l'API non può annullarlo. Annullalo dalla dashboard (Eventbrite avviserà gli iscritti via email): <dashboard_url>`, with an inline URL button `[🎟️ Apri dashboard Eventbrite]`.
- **`reactivate_on_eventbrite(context, event)`:**
  - `unpublished`: `publish_event`, then set the status to `live` and push content and capacity.
  - `closed`: restore the name with `update_event` and the capacity with a forced quantity push, then set the status to `live`.
  - `canceled`: send the admins `ℹ️ L'evento era stato annullato su Eventbrite e non può essere riattivato.` with a button `[🎟️ Ricrea su Eventbrite]` (`eb_recreate_<id>`). That button calls `clear_eventbrite_info` and then `publish_event_to_eventbrite`.
- **`discussion_booking_text(event)`:** the template lives in `utils/templates.py` as `format_discussion_booking_message(event)`. It returns `👇 Gestisci qui la tua prenotazione!`, plus `\n🎟️ Prenota anche su Eventbrite: <a href="{url}">link</a>` when `eventbrite_url` is set and the status is `live`.

### 5. Hook into existing flows
- **`bot/service/posts.py`:**
  - `update_event_messages(..., update_image=False, eventbrite_content=False)`: after the Telegram sync, call `await sync_eventbrite(context, event, content_changed=eventbrite_content, image_changed=update_image)`.
  - `_sync_discussion_reply`: switch from `edit_message_reply_markup` to `edit_message_text(text=format_discussion_booking_message(event), reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True)` on both paths: the current-query path and the stored-id path. Keep the "not modified" handling.
- **`bot/handlers/recap.py` `handle_discussion_forward`:** send `format_discussion_booking_message(event)` with `parse_mode="HTML"` and `disable_web_page_preview=True`. On the existing-reply path, edit the text as well.
- **`bot/handlers/edit.py`:**
  - Pass `eventbrite_content=field in EVENTBRITE_CONTENT_FIELDS`, where that set is `{title, date, system, host, extra_info, description, is_roleplay}`.
  - Image edits already pass `update_image`.
  - In `_edit_booked_seats` and `edit_seats` (the `X/Y` branch), raise `EditInputError` if the new booked count would be below `eventbrite_seat_count(event_id)`.
- **`bot/callbacks/events.py`:**
  - New handler `handle_publish_event_with_eventbrite`: runs the normal publish flow (factor the body of `handle_publish_event` into `_publish(query, context, event_id)`), then `publish_event_to_eventbrite`.
  - New handler `handle_eventbrite_publish`: for an already approved event.
  - New handler `handle_eventbrite_recreate`.
  - `handle_cancel_event`: after `_change_published_state`, call `cancel_on_eventbrite` if the event has an `eventbrite_event_id`.
  - `handle_reactivate_event`: call `reactivate_on_eventbrite` in the same way.
  - Use `get_approved_event_keyboard(event_id, event)` everywhere the approved keyboard is built.
- **New command `/event_publish_eventbrite [ID]`** in a new handler module, `bot/handlers/eventbrite.py`. It does exactly what `[🎟️ Pubblica su Eventbrite]` does:
  - Copy the ID resolution from `bot/handlers/story.py` (`event_regenerate_story_command`): `@admin_only()`, `resolve_message`, then `extract_event_id_from_reply(reply_msg)`, falling back to `command_argument(msg)` when it is a number. With neither, reply with usage: `❌ Rispondi al messaggio di un evento (quello con i pulsanti) oppure usa: /event_publish_eventbrite <id>`.
  - If the event is missing, reply `❌ Evento #id non trovato`. If the event is `pending`, reply `❌ Pubblica prima l'evento su Telegram (oppure usa 🚀 Publish + Eventbrite sulla scheda)`. If it is `cancelled`, reply `❌ Evento annullato: riattivalo prima`. Otherwise call the **same** `publish_event_to_eventbrite(context, event_id, msg.chat_id)` as the button. Every other check (already published, resume from draft, full or `0/0` events, date in the past, integration disabled) lives in that function, so the button and the command always behave the same way.
  - Both entry points must refresh the admin card the same way. `publish_event_to_eventbrite` should not rely on `query.message`. It updates the card through `event['admin_message_id']` with `bot.edit_message_reply_markup(chat_id=ADMIN_CHAT_ID, message_id=admin_message_id, reply_markup=get_approved_event_keyboard(event_id, event))`, ignoring "not modified" and "message to edit not found" errors.
  - Register it in `main.py` as `CommandHandler("event_publish_eventbrite", ..., block=False)`, plus a `CaptionRegex(r"^/event_publish_eventbrite(\s|$|@)")` handler, matching the other commands. Add `BotCommand("event_publish_eventbrite", "[ID] Pubblica l'evento su Eventbrite")` to `admin_commands`. Register it whether or not Eventbrite is configured; when it isn't, the shared function replies `❌ Eventbrite non configurato`.
  - Tests: `tests/bot/handlers/test_eventbrite.py` covers ID from reply, ID from argument, missing ID, pending, cancelled and not found. Patch `bot.handlers.eventbrite.publish_event_to_eventbrite` and assert it is called with the same arguments the button uses. Update `tests/test_main.py` if it checks the command list.
  - Docs: add the command to the command lists in README §4/§7, GEMINI.md and USER_QUICK_GUIDE.md.
- **`bot/callbacks/router.py`:** add `CALLBACK_ROUTES` rows for `publish_eb_event_`, `eb_publish_` and `eb_recreate_`. Check against the existing prefix-collision test.
- **`bot/keyboards.py`:**
  - `get_approval_keyboard(event_id)`: when Eventbrite is enabled, add a row `[🚀 Publish + Eventbrite]` (`publish_eb_event_<id>`).
  - `get_approved_event_keyboard(event_id, event=None)`: when enabled and no `eventbrite_event_id`, add `[🎟️ Pubblica su Eventbrite]` (`eb_publish_<id>`). When it has one, add the URL button `[🎟️ Eventbrite]` pointing to the dashboard.
  - `get_subscribers_management_keyboard(event_id, reservations, event=None)`: an Eventbrite row becomes a single URL button, `🎟️ {label} ({n})` → `attendees_dashboard_url`.
  - Update every caller, including `scripts/fix_event_keyboards.py`.
- **`utils/templates.py` `format_reservation_subscriber_display`:** prefix Eventbrite rows with `🎟️ ` in both modes. Cancellation and reactivation notices then list them as plain names automatically (`format_subscriber_tag` returns the escaped `full_name`).
- **`bot/callbacks/subscribers.py`:** no logic change needed, because the DB guard covers stale buttons. Add a line to the panel text: `🎟️ = prenotazione Eventbrite (gestisci dalla dashboard)`.

### 6. Booking poller — new `bot/service/eventbrite_poll.py` and `core/scheduler/runner.py`
- **Registration:** `runner.py` gets `add_interval_job(func, minutes, args)`, which calls `_scheduler.add_job(func, 'interval', minutes=..., args=..., max_instances=1, coalesce=True)`. In `main.py`, `post_init` registers `poll_eventbrite_bookings` with `config.EVENTBRITE_POLL_MINUTES` when Eventbrite is enabled. This keeps `core/` from importing `bot/`, so no new layering debt.
- **`poll_eventbrite_bookings(bot)`:** build `ctx = SimpleNamespace(bot=bot)`, because the existing services only use `context.bot`. Then, for each `get_eventbrite_tracked_events()` row, in a per-event `try`:
  1. Call `get_event` (Eventbrite) and `fetch_active_orders` in `to_thread`.
  2. If Eventbrite's status is `canceled` and ours is not, set ours to `canceled`. If the Telegram event is `cancelled`, tell the admins `✅ Evento #id annullato su Eventbrite (iscritti avvisati da Eventbrite)`. If the Telegram event is still `approved`, warn them `⚠️ Evento #id annullato su Eventbrite ma attivo su Telegram`.
  3. Diff the active orders against `get_eventbrite_reservations`. For every order whose seat count changed (new, more, fewer or gone), call `apply_eventbrite_order`.
  4. If anything changed, call `update_event_messages(ctx, event_id)`. That refreshes the channel post and discussion reply and pushes the corrected capacity.
     - If `EVENTBRITE_BOOKING_NOTIFICATIONS` is on, send a discussion notice for each change with `send_with_reply_fallback`. Aim it like `_notification_target` does: `discussion_chat_id` or `DISCUSSION_GROUP_ID`, replying to `discussion_message_id`.
       - Booking: `🎟️ Mario R. ha prenotato N posto/i tramite Eventbrite per: {format_event_title_link(event)}`
       - Release: `❌ Mario R. ha liberato N posto/i (Eventbrite) per: …`
     - If `overbooked`, alert the admins: `⚠️ Overbooking su #id: X/Y (prenotazione Eventbrite arrivata in contemporanea)`.
  5. Update `eventbrite_synced_at`.
  - On `EventbriteError` with `HIT_RATE_LIMIT`, log it and stop this cycle.
- **Budget:** two calls per tracked event per poll. With 10 events every 2 minutes that's about 600 calls per hour, under the 2000-per-hour limit. Document this in GEMINI.md.

### 7. Setup script — new `scripts/eventbrite_setup.py`
- `--check` validates the token (`GET /users/me/`).
- `--orgs` lists organization IDs.
- `--create-venue --name ... --address ... --city Torino --postal-code ... --country IT` prints the new `venue_id`.
- `--venues` lists existing venues.
- Follow the style of the existing scripts in `scripts/` (argparse, `core.config`).

### 8. Dates — `utils/date_utils.py`
`extract_event_datetime(event, default_time="20:45") -> datetime | None` takes the day from `normalized_date` (`parse_date_tuple_from_str`). It takes the time from the first `(\d{1,2})[:.](\d{2})` match in `event['date']`, as produced by `format_standard_event_date` or the raw AI text, and otherwise falls back to `default_time`. It returns a naive local datetime.

### 9. Docs
- **GEMINI.md:**
  - New §2.11 "Eventbrite Integration": publish, sync, poller, cancel/reactivate matrix, seat model, rate budget.
  - Update the §3 directory tree (`core/eventbrite/`, `bot/service/eventbrite*.py`, script).
  - §3.1 and §3.2 notes: the `update_event_messages` hook and the `core.eventbrite` facade.
  - §4 schema: the new columns.
  - §5 env vars.
- **README.md:** feature bullet, config block, the "New Event Flow" and "Subscriber Management" sections, and the setup script.
- **USER_QUICK_GUIDE.md:** read it first and add the admin-facing steps.
- **`.env.example`:** the new variables.
- **`requirements.txt`:** no new dependencies; `zoneinfo` is in the standard library. Add `tzdata` only if a test fails without system time-zone data.

### 10. Tests (mirror the source tree; use `tests/support` helpers)
- **`tests/support/config.py`:** add `eventbrite_credentials(**overrides)`, following the `wordpress_credentials` pattern.
- **`tests/core/eventbrite/`:**
  - `test_payload.py`: start/end with and without a time and in the past; `ticket_quantity` cases (limited, unlimited, cancelled, Eventbrite seats above capacity); display names; HTML escaping; name truncation.
  - `test_client.py`: patch `core.eventbrite.client.requests`; cover the error parsing and pagination.
  - `test_orders.py`, `test_media.py`.
- **`tests/core/db/`:**
  - `test_schema.py`: the migrations add the columns and the index.
  - `test_seats.py`: `apply_eventbrite_order` (new, increase, decrease, delete, overbooked, cancelled event); admin ± refused on Eventbrite rows; `unbook_seat` doesn't match Eventbrite rows.
- **`tests/bot/service/`:**
  - `test_eventbrite.py`: publish happy path and resume-from-draft; publish refused for a `0/0` event and for an event fully booked on Telegram (no HTTP calls made), but allowed for an unlimited one; sync skips the push when the quantity is unchanged; the cancel branches (no orders → unpublish; orders and cancel succeeds; orders and cancel refused → dashboard alert); the reactivate branches.
  - `test_eventbrite_poll.py`: diff → notices on and off, overbooking alert, Eventbrite-side cancellation detection, rate-limit stop.
  - `test_posts.py`: the discussion text includes the link; `sync_eventbrite` is called and makes no HTTP calls when the event has no Eventbrite id.
- **Updates to existing tests:**
  - `tests/bot/test_keyboards.py`, `tests/bot/callbacks/test_events.py`, `test_router.py`.
  - `tests/bot/handlers/test_edit.py`: booked count below Eventbrite seats is rejected; content flag.
  - `test_recap.py`: discussion forward text.
  - `tests/utils/test_date_utils.py`, `test_templates.py`, `test_image_utils.py` (`pad_to_aspect` gives 2:1).
- The suite must run without network or tokens. Patch `core.eventbrite.*` functions where they are **used**, e.g. `bot.service.eventbrite.create_event`.

---

## Critical files
- **New:**
  - `core/eventbrite/{__init__,client,payload,events,tickets,media,orders}.py`
  - `bot/service/eventbrite.py`, `bot/service/eventbrite_poll.py`, `bot/handlers/eventbrite.py` (`/event_publish_eventbrite`)
  - `scripts/eventbrite_setup.py`
- **Modified:**
  - `core/config.py`, `core/db/{schema,events,seats,reservations,__init__}.py`, `core/scheduler/runner.py`, `main.py`
  - `bot/service/posts.py`, `bot/callbacks/{events,router,subscribers}.py`, `bot/keyboards.py`, `bot/handlers/{edit,recap}.py`
  - `utils/{templates,date_utils,image_utils}.py`, `scripts/fix_event_keyboards.py`
  - Docs and `.env.example`
- **Reuse:**
  - `_load_seat_state` / `_set_booked_seats` (`core/db/seats.py`)
  - `send_with_reply_fallback` (`bot/common/messages.py`), `send_discussion_notice` (`bot/service/notices.py`)
  - `format_event_title_link` (`utils/templates.py`), `create_collage`-style Pillow helpers (`utils/image_utils.py`)
  - `asyncio.to_thread` pattern (`core/instagram.py`)
  - `@db_safe` / `transaction()` (`core/db/connection.py`), `patched_config` (`tests/support/config.py`)

## Verification
1. Run `python3 -m pytest tests`. Everything must pass, including the existing suite, both with Eventbrite unconfigured (no behaviour change, no new buttons) and with it configured.
2. **Manual end-to-end test** against a real Eventbrite account, using `EVENTBRITE_LISTED=false`. Eventbrite has no sandbox, so this test also confirms the unverified points listed in Context.
   1. `python3 scripts/eventbrite_setup.py --check --orgs`, then `--create-venue`, then fill in `.env`.
   2. `/ep` a test event, then `[🚀 Publish + Eventbrite]`. Check the event page (title, date and time in Europe/Rome, description, 2:1 logo, quantity) and the link in the discussion reply. The channel post must have no link.
   - Publish a second test event to Telegram only, then reply to its admin card with `/event_publish_eventbrite`, and also try `/event_publish_eventbrite <id>`. The result must match the button: same link, the admin card switches to `[🎟️ Eventbrite]`, and a second run replies with the existing link instead of creating a duplicate.
   3. Book one seat in Telegram. Within seconds the Eventbrite remaining count drops by 1.
   4. Register on Eventbrite with 2 tickets. Within `EVENTBRITE_POLL_MINUTES` the channel post seats update and the discussion shows `🎟️ Nome I. ha prenotato 2 posti…`. Set `EVENTBRITE_BOOKING_NOTIFICATIONS=false` and confirm the notice is gone while seats still sync.
   5. Cancel the order as the attendee on Eventbrite. The seats come back and the release notice appears.
   6. `/event_edit_title`, `/event_edit_date`, `/event_edit_image`, `/event_edit_seats`. Each one is reflected on Eventbrite. Also try a date change while an order exists.
   7. 👥 Gestisci Iscritti: the Eventbrite row is a URL button that opens the dashboard.
   8. `❌ Annulla Evento` with no Eventbrite orders: the event is unpublished, and `♻️ Riattiva` republishes it. With orders: sales close, the event is renamed and the cancel API is tried; if it's refused, the dashboard link arrives. After the manual cancel in the dashboard, the poller confirms it. `♻️ Riattiva` then offers `[🎟️ Ricrea su Eventbrite]`.
   9. Fill the event until it's full from both sides and check that both show full. A deliberate near-simultaneous booking should trigger the overbooking alert.
3. After approval, save this plan in the repository as `docs/plans/eventbrite-integration.md`.
