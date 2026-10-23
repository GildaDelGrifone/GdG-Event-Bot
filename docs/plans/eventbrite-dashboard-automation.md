# Draft plan: cancel Eventbrite orders by automating the organizer dashboard (future work)

> Status: **draft, not scheduled**. Today the bot sends the admins one "Cancel order" link per order (see GEMINI.md §2.11). This plan is the optional next step: the bot cancels the orders itself by driving the organizer dashboard.

## Context
- Eventbrite's public API (v3) has **no call to cancel an order or attendee**. The only per-order write call is `POST /orders/{id}/refunds/`, and it **fails on free orders**, which is what our events use (confirmed on a real account).
- `POST /events/{id}/cancel/` is refused while the event has any order. So a Telegram cancellation of an event with Eventbrite bookings ends in the `closed` state. The admins then cancel each order by hand, and the bot completes the event cancellation (`finish_eventbrite_cancellation`).
- The dashboard *can* cancel an order. Confirmed URLs:
  - event dashboard: `https://www.eventbrite.com/events/{eid}/dashboard/?eid={eid}`
  - order details: `https://www.eventbrite.com/organizations/orders/{oid}`
  - cancel page: `https://www.eventbrite.com/order-cancel?eid={eid}&oid={oid}&aid=` → after confirming it lands on `https://www.eventbrite.com/reports?eid={eid}&rid=h`
- These pages use the logged-in **browser session**, not the API token. Automating them means driving a real (headless) browser on the organizer's own profile.

## Terms of Service: read before implementing
Eventbrite Terms of Service (https://www.eventbrite.com/help/en-us/articles/251210/eventbrite-terms-of-service/):
- **13.1:** "you agree not to, scrape, crawl, or employ any automated means to extract data from the Sites". This targets **data extraction**. Cancelling our own orders is not extraction, so it is not clearly covered.
- **10.2(5):** no activity that "interferes with or disrupts the Services".
- **4.2:** Eventbrite may suspend or terminate access for use "in a way not intended or permitted by us".
- There is no explicit exception for account owners automating their own account.

**Risk:** this is not mainly legal. The **organizer account that hosts every event** could be flagged or suspended. **Before building:** ask Eventbrite support whether automating "Cancel order" on our own account is acceptable, and record the answer here. (Not legal advice.)

## Goals and non-goals
- Goal: after the admin's Telegram confirmation, cancel every active order of a Telegram-cancelled event without manual clicks. Eventbrite still sends its own cancellation email to each attendee.
- Goal: never be the only path. Any failure falls back to today's per-order links.
- Non-goals: refunds of paid orders, bulk actions across events, any data extraction beyond what the API already gives us, storing the organizer's password.

## Design

### Opt-in configuration
```
EVENTBRITE_DASHBOARD_AUTOMATION=false     # master switch (off by default)
EVENTBRITE_DASHBOARD_PROFILE_DIR=         # persistent browser profile, e.g. [DATA_DIR]/eventbrite_profile (git-ignored, chmod 700)
EVENTBRITE_DASHBOARD_DRY_RUN=false        # open pages and find the buttons, but do not click "confirm"
EVENTBRITE_DASHBOARD_DELAY_SECONDS=5      # pause between orders
```
`dashboard_automation_enabled()` = the switch is on, `eventbrite_enabled()`, and the profile dir exists. Read at call time from `core.config`, like every other setting.

### Session handling (no password in the bot)
- A one-off helper, `scripts/eventbrite_dashboard_login.py`, opens a **headed** Chromium with the persistent profile dir. A human logs in, including 2FA or captcha, and closes the window. The session cookies stay in the profile.
- The bot only reuses that profile, headless. When the session expires (redirect to the login page), the bot stops, falls back to the links, and tells the admins to rerun the login script.
- The bot never stores, types or logs credentials.

### New module `core/eventbrite/dashboard.py` (blocking; callers use `asyncio.to_thread`)
- Dependency: `playwright` (sync API) plus `playwright install chromium`. It is **optional**: the import happens inside the function, so the bot runs without it when the feature is off.
- `cancel_order_via_dashboard(eb_event_id, order_id, dry_run=False) -> DashboardResult`:
  1. `launch_persistent_context(profile_dir, headless=True)`, then open `order_cancel_url(eid, oid)` (`core/eventbrite/payload.py`).
  2. Detect states:
     - the login page → `SESSION_EXPIRED`;
     - a captcha or bot check → `BLOCKED`;
     - the order is already cancelled → `ALREADY_CANCELLED`;
     - the confirm button is missing → `PAGE_CHANGED`.
  3. Unless dry run, click the confirm button and wait for navigation to `reports?...&rid=h` (or a success marker) → `CANCELLED`.
  4. On any failure, take a screenshot into `[DATA_DIR]/logs/eventbrite_dashboard/` (no personal data in file names) and return the status.
- All selectors and texts live in **one constant table** (`SELECTORS`), with Italian and English labels, so a UI change is a one-line fix.
- One browser context per batch, not per order. Pause `EVENTBRITE_DASHBOARD_DELAY_SECONDS` between orders, and stop the batch on `SESSION_EXPIRED` / `BLOCKED`.

### Telegram flow (`bot/service/eventbrite.py`, `bot/callbacks/events.py`)
- When automation is enabled, the existing `closed` message (`_orders_cancel_message`) gets an extra button: `[🤖 Annulla ordini automaticamente]` (`eb_auto_cancel_<event_id>`). It is a separate, explicit action, on top of the cancel confirmation that already exists.
- `auto_cancel_orders(context, event, admin_chat_id)`:
  1. `fetch_active_orders` gives the list to cancel. The API stays the source of truth.
  2. Call `cancel_order_via_dashboard` for each order, in `asyncio.to_thread`, while editing a progress message (`2/5 ordini annullati…`).
  3. Re-check with `fetch_active_orders`. Eventbrite is eventually consistent, so re-check after a short wait if needed.
  4. With no orders left, `finish_eventbrite_cancellation` (existing) cancels the event and notifies the admins.
  5. Otherwise, re-send `_orders_cancel_message` with only the orders still active, plus the reason (e.g. "sessione scaduta: esegui scripts/eventbrite_dashboard_login.py").
- A lock per event, so a double click cannot start two batches.
- The poller needs no change: it already completes the cancellation once no orders remain.

### Logging and audit
- Log who pressed the button (`describe_user`), each order id and result status. Never log names or emails.
- Optional: `eventbrite_dashboard_runs` rows (event_id, started_at, results JSON) for traceability.

## Tests
- Unit, with Playwright mocked through a fake page object exposing `goto`, `locator`, `click` and `wait_for_url`. Cover:
  - each result status (cancelled, already cancelled, session expired, blocked, page changed, dry run);
  - the batch stops on an expired or blocked session;
  - the delay between orders.
- Service: `auto_cancel_orders` with mocked `cancel_order_via_dashboard` / `fetch_active_orders`. Cover:
  - all cancelled → `finish_eventbrite_cancellation` called;
  - partial → links re-sent for the remainder;
  - the lock prevents a second run.
- Keyboard: the `🤖` button only when automation is enabled; router prefix `eb_auto_cancel_` with no collision.
- The suite stays offline: no real browser in CI. A separate, manually-run `scripts/` smoke test for a real account.

## Manual verification (test event, `EVENTBRITE_LISTED=false`)
1. Run the login script and log in once, then check that `EVENTBRITE_DASHBOARD_PROFILE_DIR` exists.
2. Dry run on an event with 2 orders: the screenshots show the confirm button found, and nothing is cancelled.
3. Real run: both orders end up cancelled in the dashboard, the attendees get Eventbrite's email, the event becomes `canceled`, and the admins get the ✅ message.
4. Expire the session (delete cookies): the bot falls back to the links and asks for a new login.
5. Change one selector to simulate a UI change: the result is `PAGE_CHANGED`, the links fall back, and a screenshot is saved.

## Open questions
- Exact texts and selectors of the confirm button on the Italian and English UI, and whether the page needs a non-empty `aid`.
- How long the dashboard session lasts, and whether Eventbrite asks for re-authentication on new or headless devices.
- Whether Eventbrite rate-limits or flags repeated cancels from one session.
- Eventbrite support's answer on automation (see the Terms section).
- Hosting: Chromium needs about 300 MB of disk and some RAM on the bot server. Check the target machine.
