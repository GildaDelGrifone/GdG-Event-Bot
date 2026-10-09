# GdG-Event-Bot - Technical Specification & Architecture Guide

## Table of Contents
- [1. Project Overview](#1-project-overview)
- [2. End-to-End Workflows](#2-end-to-end-workflows)
  - [2.1. Event Ingestion & Interception](#21-event-ingestion--interception)
  - [2.2. AI Parsing (`core/ai_parser.py`)](#22-ai-parsing-coreai_parserpy)
  - [2.3. Admin Review & Approval (`bot/callbacks/events.py`)](#23-admin-review--approval-botcallbackseventspy)
  - [2.4. Interactive Live Booking System](#24-interactive-live-booking-system)
  - [2.5. Cancellation System](#25-cancellation-system)
  - [2.6. Daily Recap Generation (`core/scheduler/recap.py` & `bot/handlers/recap.py`)](#26-daily-recap-generation-coreschedulerrecappy--bothandlersrecappy)
  - [2.7. Post-Recap WordPress & Story Pipeline (`bot/callbacks/recap.py`)](#27-post-recap-wordpress--story-pipeline-botcallbacksrecappy)
  - [2.8. Nightly Image Archiving (`core/scheduler/archive.py` & `unzip_images.py`)](#28-nightly-image-archiving-coreschedulerarchivepy--unzip_imagespy)
  - [2.9. Daily Log Rotation & Monthly Log Archiving (`core/log_utils.py` & `core/scheduler/archive.py`)](#29-daily-log-rotation--monthly-log-archiving-corelog_utilspy--coreschedulerarchivepy)
  - [2.10. Event Reposting & Repost Scheduling (`bot/handlers/repost*.py` & `core/scheduler/reposts.py`)](#210-event-reposting--repost-scheduling-bothandlersrepostpy--coreschedulerrepostspy)
- [3. Directory Structure](#3-directory-structure)
  - [3.1. `bot/` Package Architecture](#31-bot-package-architecture)
  - [3.2. `core/` Package Architecture](#32-core-package-architecture)
- [4. Database Schema (SQLite: `bot_database.db`)](#4-database-schema-sqlite-bot_databasedb)
- [5. Environment Variables (`.env`)](#5-environment-variables-env)
- [6. Templates & Character Limit Handling](#6-templates--character-limit-handling)
- [7. Instagram Story Publishing Status & Unpause Guide](#7-instagram-story-publishing-status--unpause-guide)

---

## 1. Project Overview
**GdG-Event-Bot** is a continuously running Python application designed for **Gilda del Grifone**, a tabletop games association based in Turin (Italy).

The system automates the ingestion, standardization, social sharing, and booking management of tabletop gaming events:
- Intercepts and parses unstructured event announcements from a Telegram public channel or admin chat using Google Gemini AI.
- Re-publishes standardized event announcements to the public channel with interactive inline buttons for live seat reservations.
- Tracks reservations per user and manages seat availability in real time.
- Compiles daily recap messages and multi-image collages on game days (Mon, Wed, Fri, Sat, Sun).
- Generates Instagram Story images (1080x1920) for both individual events and daily recaps using Pillow.
- Generates engaging recap articles using Gemini AI and drafts/publishes them on WordPress via the WordPress REST API.

---

## 2. End-to-End Workflows

### 2.1. Event Ingestion & Interception
1. **Public Channel Interception (`bot/handlers/ingestion.py`, `albums.py`, `extraction.py`):**
   - The bot listens to `PUBLIC_CHANNEL_ID`.
   - When an admin posts a message with text and an image:
     - **Programmatic Pre-Filters:**
       - Checks if the bot is paused (`/bot_pause`). If paused, the message is ignored.
       - Checks if the message was sent by a bot (`from_user.is_bot`). If so, it is ignored.
       - Checks if the message already contains booking callback buttons (`book_` / `unbook_`). If so, it ignores it.
       - **Event Keywords Check (`contains_event_keywords`):** Checks if the text contains at least one recognized event keyword (case-insensitive, colon optional whitespace):
         - Colon keywords: `Titolo:`, `Posti:`, `Posti liberi:`, `Descrizione:`, `Sinossi:`, `Gioco:`, `Quando:`, `Data:`
         - Phrase keywords: `Gioco da tavolo`, `Gioco di ruolo`, `Oneshot`, `One shot`
         - If none of these keywords are present, the message is ignored and the AI call is completely skipped, saving API quota.
     - **AI Event Confirmation & Deferred Deletion:** For messages passing the pre-filters, the post is evaluated by Gemini AI (`core/ai_parser.py`):
       - **If confirmed as an event (`is_event != False`):** The original raw message(s) are deleted from the public channel to avoid unformatted duplicates, and the event is routed to admin review.
       - **If not an event (`is_event == False` or unparseable):** The post is considered a general announcement, reminder, or notice and is preserved intact in the channel without deletion or database insertion.
     - **Multi-Image Media Groups (Albums 2–4 photos):** When an event arrives with multiple photos sharing a `media_group_id`, updates and message references are aggregated in memory across a 2-second silence buffer. If Gemini confirms the post is an event, all aggregated messages in the album are batch-deleted together. Once aggregated, `utils/image_utils.create_collage_from_bytes` builds a uniform horizontal collage (matching recap collage rules: uniform average height, preserved individual aspect ratios, no cropping or distortion). Only the stitched collage is saved as `event_{uuid}.jpg` in `[DATA_DIR]/YYYY/MM/DD/`; individual raw photos are never written to disk.
     - **Single Photo:** The image is downloaded and saved directly to `[DATA_DIR]/YYYY/MM/DD/event_{uuid}.jpg`.
     - The text is passed to `core/ai_parser.py`.
2. **Manual Ingestion (`/event_process` or `/ep`):**
   - An admin can send an image or multi-image album with text to `ADMIN_CHAT_ID` and reply `/event_process` or `/ep` (or include text directly in the command: `/ep <testo>`).
   - Photos/albums sent in `ADMIN_CHAT_ID` are silently cached in memory. When replying with `/ep` to any photo in an album, the bot aggregates all sibling photos of that `media_group_id`, stitches them into a horizontal collage using `utils/image_utils.create_collage_from_bytes`, and resolves text from the command, replied message, or album captions.
   - **Note:** Manual triggers bypass the keyword pre-filter, enabling admins to process events with non-standard formatting.
   - Operates through the identical parsing and review pipeline.
3. **AI Event Generation (`/event_generate` or `/eg`):**
   - Admins can send `/event_generate <istruzioni>` or `/eg <istruzioni>` (or reply to a message with the command) in `ADMIN_CHAT_ID`.
   - Handled in the `bot/event_generator/` package (`command.py` → `pipeline.py`, using `ai.py` and `bgg.py`):
     - Gemini AI interprets natural language instructions (games, date, host, seats, extra info, RPG vs board game) and writes an engaging synopsis/pitch in Italian constrained to <= 400 characters.
     - For each identified game, queries the BoardGameGeek JSON API (`https://api.geekdo.com/api/geekitems`) to find the best match and download the official box cover image.
     - If multiple games were requested, builds a uniform horizontal collage via `utils/image_utils.create_collage_from_bytes`. If a single game was requested, preserves the single image without collaging.
     - Programmatically guarantees the entire formatted event caption stays within Telegram's 1024-character caption limit via `enforce_caption_limit()`.
     - Inserts the generated event as `pending` into SQLite and sends the preview card to `ADMIN_CHAT_ID` with standard approval buttons (`[Publish]`, `[Discard]`, `[👥 Gestisci Iscritti]`).
4. **Monitoring Pause / Resume (`/bot_pause`, `/bot_resume`, `/bot_status`):**
   - Admins can send `/bot_pause` in `ADMIN_CHAT_ID` to make the bot temporarily "blind" to `PUBLIC_CHANNEL_ID` (it will not intercept, parse, or delete messages from the channel).
   - Send `/bot_resume` to re-enable interception, and `/bot_status` to check the current operational state.

### 2.2. AI Parsing (`core/ai_parser.py`)
- Model configured via `GEMINI_MODEL` (default: `gemini-3.1-flash-lite`).
- Returns structured JSON:
  - `is_event` (bool): If `false`, non-event messages are ignored.
  - `title` (string): Event/Game title.
  - `date` (string): Raw Italian date string (e.g. `09 Settembre 21.00`).
  - `normalized_date` (string): Strict `DD-MM-YYYY` date for scheduling and folder organization.
  - `system` (string): Game system / genre (e.g. `Call of Cthulhu 7a Ed.`, `Board Game`).
  - `host` (string): Master/Host name or handle.
  - `seats` (string): Normalized string representing available seats (e.g. `4/4` or `0/0 Completo`).
  - `booked_seats` (int): Initialized to 0 for bot-managed seats.
  - `max_seats` (int or null): Bookable capacity matching the free seats specified at announcement time (e.g. if `Posti liberi: 4/5` or `2/4` is posted, `max_seats` is set to `4` or `2`, ignoring table totals `Y` since the bot only tracks open slots; `booked_seats` starts at 0).
    - `Posti: 2/2` or `Posti liberi: 3/3` -> `booked_seats: 0`, `max_seats: 2` or `3`.
    - `Posti liberi: 4/5` -> `booked_seats: 0`, `max_seats: 4`.
    - `Posti liberi: 2/4` -> `booked_seats: 0`, `max_seats: 2`.
    - `Posti liberi: 0/3 Completo` -> `booked_seats: 0`, `max_seats: 0`.
    - A deterministic regex safety net enforces `max_seats = free` and `booked_seats = 0` in `core/ai_parser.py`.
  - `extra_info` (string): Additional details (difficulty/beginner friendliness, format/duration/campaign, trigger warnings/disclaimers/X-Card, genres).
  - `description` (string): Event pitch/synopsis.
  - `is_roleplay` (boolean): `true` if the event is a tabletop roleplaying game (displays as `Master:`), `false` if it is a board game or other non-RPG event (displays as `Host:`).
- **Quota / Credit Depletion Handling:**
  - If Google Gemini returns HTTP 429 or prepayment credits are depleted (`GeminiQuotaError`), the bot alerts admins immediately in `ADMIN_CHAT_ID`:
    ```
    🚨 Errore Gemini AI (Crediti esauriti):
    429 Your prepayment credits are depleted.
    ```
  - This alert is triggered during event parsing (`handle_event_extraction`) and recap WordPress article generation (`bot/callbacks/recap.py`), via the shared `notify_quota_depleted` helper in `bot/common/previews.py`.

### 2.3. Admin Review & Approval (`bot/callbacks/events.py`)
- For messages intercepted and deleted from `PUBLIC_CHANNEL_ID`, the raw `original_text` of the event is sent to `ADMIN_CHAT_ID` as a separate message so admins can verify if the AI made any mistakes (omitted for manual `/event_process` or `/ep` triggers where the original message is already in `ADMIN_CHAT_ID`).
- Then, the parsed event is sent to `ADMIN_CHAT_ID` with inline keyboard buttons: `[Publish]`, `[Discard]`, `[Cancel]`, and `[👥 Gestisci Iscritti]`.
- For privacy, the `Master/Host` field is omitted from generated Instagram Story images, but is displayed in the admin review message and the public channel post.
- **[Discard]:** Deletes the local event image, permanently deletes the event and all associated reservations from SQLite database, updates message to `❌ SCARTATO` and removes inline action buttons.
- **[Cancel]:** Updates DB status to `cancelled`, updates message to `⚠️ ANNULLATO`, switches keyboard to `[♻️ Riattiva Evento]` and `[👥 Gestisci Iscritti]`, and posts a notice to `DISCUSSION_GROUP_ID` tagging all subscribers.
- **[Publish]:**
  1. Generates 1080x1920 Instagram Story image using `utils/image_utils.create_story_image()` and saves it in `[DATA_DIR]/YYYY/MM/DD/`.
  2. Sends the generated story image to `ADMIN_CHAT_ID` for review *(Meta Graph API publishing is currently commented out for testing; see section 6)*.
  3. Formats the official standardized public channel post using `utils/templates.format_public_event_post()`.
  4. Posts the formatted message with the original image to `PUBLIC_CHANNEL_ID`, attaching the `[➕ Prenota] [👥 Lista] [➖ Annulla]` inline keyboard.
  5. Updates DB with the public `telegram_message_id` and `message_link`.
  6. Leaves persistent `[❌ Annulla Evento]` and `[👥 Gestisci Iscritti]` buttons under the admin review message.

### 2.4. Public Booking, Deep-Link Participant List & Same-Day Conflict Warnings
- **Seat Booking (`[➕ Prenota]` / `book_<event_id>` or `[🚫 Esauriti]` / `full_<event_id>`):**
  - Increments seat reservation count for the user in `reservations` table.
  - Updates remaining seat counter on the public channel post and discussion message.
  - Posts a booking confirmation notification to `DISCUSSION_GROUP_ID` (e.g. `✅ @user ha prenotato 1 posto per: <b>Titolo</b>`, where the bold title is hyperlinked to the event post if available).
- **Deep-Link Participant List (`[👥 Lista]` -> `t.me/{bot_username}?start=subs_{event_id}`):**
  - Opens a 1-on-1 private chat with the bot and executes `/start subs_{event_id}`.
  - Bot responds directly in DM with a formatted overview of current subscribers and seat counts, completely avoiding chat spam in public channels and discussion groups.
- **Direct Participant List Command (`/event_subs <event_id>` or `/subs <event_id>` / `/event_subs_<event_id>`):**
  - Allows users or admins to manually query the participant list for any event by ID in private chat or discussion group.
- **Deep-Link Upcoming Events (`t.me/{bot_username}?start=event_next`):**
  - Opens a 1-on-1 private chat with the bot and executes `/start event_next`, which triggers `/event_next` and displays all today's and upcoming scheduled events directly in DM. Each event in the `/event_next` listing includes direct deep links (`start=subs_{id}`) and clickable `/event_subs {id}` commands for instantaneous roster access.

- **Same-Day Conflict Warnings (`get_user_conflicting_events` & `send_conflict_warning`):**
  - When a user reserves a seat, the system checks whether the user already holds active reservations (`seats_booked > 0`) for any other valid events (`status NOT IN ('cancelled', 'discarded')`) scheduled on that exact same day.
  - Handles date comparison across date formats (`DD-MM-YYYY` vs `YYYY-MM-DD`).
  - If conflicting events are detected, the subscription is **still processed normally**, and a formatted warning message is immediately sent to `DISCUSSION_GROUP_ID` tagging the user:
    - Informs them they are already registered for other event(s) on that day.
    - Lists all conflicting events with their bold titles (hyperlinked to the respective posts if available) and systems.
    - Advises the user to release their seat from whichever event they decide not to attend.
- **Seat Release (`[➖ Annulla]` / `unbook_<event_id>`):**
  - Decrements seat reservation count or deletes reservation record if 0 seats remain.
  - Updates remaining seats on public channel post and discussion message.
  - Posts a release notification to `DISCUSSION_GROUP_ID` (e.g. `❌ @user ha liberato 1 posto per: <b>Titolo</b>`, where the bold title is hyperlinked to the event post if available).

### 2.5. Admin Subscriber Management
- **`[👥 Gestisci Iscritti]` Button (`manage_subs_<event_id>`):**
  - Displays event status, total booked seats vs max seats, and a detailed list of all subscribers and their seat counts.
  - Generates inline buttons for each subscriber: `[➖ @user (N)]` and `[➕ @user (N)]` to quickly increment or decrement seats.
  - Includes a `[➕ Aggiungi Iscritto]` button that sends a `ForceReply` prompt allowing admins to register any user by typing their `@username` (with optional seat count).
  - Includes `[🔄 Aggiorna]` and `[❌ Chiudi]` buttons.
- **Commands:**
  - `/event_sub_add <event_id> @username [posti]` - also works in reply to an event message without `<event_id>`.
  - `/event_sub_remove <event_id> @username [posti]` - also works in reply to an event message without `<event_id>`.
- **Public Group Notifications (`send_admin_action_notice` in `bot/service/notices.py`):**
  - When an event admin adds or removes subscribers or seats for a public event, a notification is posted to `DISCUSSION_GROUP_ID` (replying to `discussion_message_id` if available).
  - Explicitly states that the action was performed by an **event admin** (`admin degli eventi`) to avoid confusion with group or server administrators, tags the target user, specifies the seat count, and formats the event name in bold hyperlinking to the event post if available.

### 2.6. Cancellation & Reactivation System
- **Cancellation (`[Cancel]` / `[❌ Annulla Evento]`):**
  - Admins can click Cancel on any event.
  - Status set to `cancelled` in DB.
  - Live public post is updated with `❌ [ANNULLATO]` and `🪑 Posti: 0/<max_seats> [ANNULLATO]`, and booking buttons are removed.
  - A notification is sent to the public discussion group (`DISCUSSION_GROUP_ID`) where all subscribed Telegram users are tagged and informed of the cancellation with the bold event title (hyperlinked to the event post if available, `disable_web_page_preview=True`). If no subscribers, sends a general cancellation notice.
  - Admin post keyboard changes to `[♻️ Riattiva Evento]` and `[👥 Gestisci Iscritti]`.
- **Reactivation (`[♻️ Riattiva Evento]`):**
  - Under a cancelled event in `ADMIN_CHAT_ID`, admins can click `[♻️ Riattiva Evento]`.
  - Status set back to `approved` in DB.
  - Live public post and discussion group message are restored with active booking buttons.
  - A notification is sent to the public discussion group (`DISCUSSION_GROUP_ID`) tagging the original subscribers to inform them that the event has been reactivated with the bold event title (hyperlinked to the event post if available, `disable_web_page_preview=True`). If no subscribers, sends a general reactivation notice.
  - Admin post keyboard switches back to `[❌ Annulla Evento]` and `[👥 Gestisci Iscritti]`.

### 2.7. Daily Recap Generation (`core/scheduler/recap.py` & `bot/handlers/recap.py`)
1. **Triggering:**
   - **Automatic:** Scheduled daily at **16:00** via APScheduler. Automatically checks if today is Monday, Wednesday, Friday, Saturday, or Sunday. Remains silent if no events are scheduled.
   - **Manual:** Triggered via `/recap_generate` (or `/rg`) or `/recap_generate DD-MM-YYYY` / `/rg DD-MM-YYYY` (bypasses weekday check). If no events are scheduled for today (or the target date), notifies the admin directly in `ADMIN_CHAT_ID` (`Nessun evento in programma per oggi.`) without generating an empty recap.
2. **Data Aggregation:**
   - Queries `events` table for all `approved` and `cancelled` events where `normalized_date == date_str`.
3. **Collage Assembly (`utils/image_utils.create_collage`):**
   - Collects images for all matching events.
   - Resizes images to a uniform average height preserving individual aspect ratios (no distortion, no cropped borders).
   - Arranges images into rows based on `MAX_EVENTS_PER_ROW` (centering shorter rows for a balanced layout) and saves to `[DATA_DIR]/YYYY/MM/DD/recap_collage_DD-MM-YYYY.jpg`.
4. **Text Formatting (`utils/templates.recap_generate_text` & `recap_links_text`):**
   - Italian day names (Lunedì, Mercoledì, etc.).
   - Lists events in caption with bold titles and live available seats: `- <b>Titolo</b> (Sistema) : X/Y` (or `- ❌ <b>Titolo</b> (Sistema) : X/Y [ANNULLATO]`).
   - Generates comment text `recap_links_text` listing all active events with bold hyperlinked titles: `- <a href="..."><b>Titolo</b></a> (Sistema)`.
   - If recap caption length exceeds Telegram's 1024-character caption limit, automatically falls back to slim recap format.
5. **Approval:**
   - Sends collage + recap text to `ADMIN_CHAT_ID` with `[Publish Recap]` and `[Discard Recap]`.

### 2.7. Post-Recap WordPress & Story Pipeline (`bot/callbacks/recap.py`)
When `[Publish Recap]` is clicked:
1. **Public Telegram Recap:** The collage + text is published to `PUBLIC_CHANNEL_ID`. The links message (`recap_links_text`) is NOT posted to the public channel; it is sent exclusively as a reply to the automatic channel forward in the Discussion Chat group (`DISCUSSION_GROUP_ID`).
2. **Instagram Recap Story:**
   - `utils/image_utils.create_recap_story_image()` builds a 1080x1920 canvas.
   - Collage pinned at top, header `Proposte del [Data]`, bulleted event list with seats, and footer:
     `Ci vediamo alle 20:45, alla Gilda del Grifone in Via Ada Negri 8/A, Torino!`
   - Sent to `ADMIN_CHAT_ID` for review.
3. **WordPress Article Generation (`core/wordpress/` & `core/ai_parser.py`):**
   - Uploads each individual event image to WordPress Media Library (style set to max 400x400px).
   - Uploads the recap collage as `featured_media`.
   - Calls Gemini AI with event details, links, and image URLs to write an engaging recap article in Italian.
   - Creates a WordPress post as `draft`.
   - Updates `wp_post_id` and `wp_post_url` in the database.
   - Sends editor link to `ADMIN_CHAT_ID` with inline button `[Pubblica su WordPress]`.
4. **WordPress One-Click Publish:**
   - Clicking `[Pubblica su WordPress]` changes post status from `draft` to `publish` via REST API.

### 2.8. Nightly Image Archiving (`core/scheduler/archive.py` & `scripts/unzip_images.py`)
- Automatically runs daily at **23:59** via APScheduler.
- Checks today's folder (`[DATA_DIR]/YYYY/MM/DD/`) for images (`.jpg`, `.jpeg`, `.png`, `.webp`).
- Compresses them into `archive.zip` inside the same folder and removes the original loose image files to save disk space.
- Utility script `scripts/unzip_images.py` allows restoring images from `archive.zip` by specifying a folder, date, or date range.

### 2.9. Daily Log Rotation & Monthly Log Archiving (`core/log_utils.py` & `core/scheduler/archive.py`)
- Application logging is recorded simultaneously to stdout/terminal and daily log files in `[DATA_DIR]/logs/bot.log`.
- Log files rotate daily at midnight via `DailyMonthlyLogHandler` (`TimedRotatingFileHandler`).
- Upon each daily rotation (as well as on startup and via a nightly check at 00:05 in `core/scheduler/archive.py`), the system checks whether the previous month has ended.
- Daily logs from ended months are aggregated and compressed into `[DATA_DIR]/logs/bot_logs_YYYY-MM.zip`, and the loose daily log files for that month are deleted to save disk space.

### 2.10. Event Reposting & Repost Scheduling (`bot/handlers/repost*.py` & `core/scheduler/reposts.py`)
- **Direct Reposting (`/event_repost DATE SEATS` or `/er DATE SEATS`):**
  - Allows admins to reply to any event announcement or bot preview to re-process and repost it with a single command.
  - Groups AI parsing (`/event_process`), date modification (`/event_edit_date`), and seats capacity adjustment (`/event_edit_seats`) into one operation.
  - Supports calendar dates (`DD-MM-YYYY [HH:MM]`), `"oggi"` (today), and relative weekday shortcuts `"LUN"`, `"MER"`, `"VEN"` (which target the next upcoming Monday, Wednesday, or Friday, skipping today if it's already that weekday).
  - `SEATS` accepts `X/Y`, a bare integer (free = total), or an unlimited token (`null`, `nessuno`, `illimitati`, `unlimited`, `none`, `0`), parsed by the same `parse_seats_input` helper as `/event_edit_seats`. Unlimited seats display as `no limit`.
  - Prompts admin for confirmation via standard approval buttons (`[Publish]`, `[Discard]`, `[👥 Gestisci Iscritti]`).
- **Interactive Repost Scheduling (`/event_schedule`):**
  - Replying to an event message with `/event_schedule` opens an interactive management card with inline toggle buttons:
    - Line 1: `[Lunedì] [Mercoledì] [Venerdì]` (standard opening days).
    - Line 2: `[Sabato] [Domenica]` (special opening days).
    - Buttons display dynamic emoji checkboxes (`✅` when active, `⬜` when inactive) to toggle recurring schedule days.
  - Admins can also specify a one-off scheduled date via `/event_schedule [ID] DD-MM-YYYY [HH:MM]`.
- **Scheduled Repost Notification & Invocation (10:00 AM Cron):**
  - Runs daily at **10:00 AM** via APScheduler.
  - Queries `scheduled_events` for entries matching today's date or active weekday.
  - Sends a consolidated digest to `ADMIN_CHAT_ID` listing each scheduled event with a clickable invocation command: `/event_schedule_invoke <SCHEDULED_ID>`.
  - Invoking `/event_schedule_invoke <SCHEDULED_ID>` prepares the event with date set to today and outputs the approval card ready for publishing.
- **Scheduled Content Overwrite (`/event_schedule_update <SCHEDULED_ID>`):**
  - Admins can reply to any new event post with `/event_schedule_update <SCHEDULED_ID>` to overwrite the text and image template of an existing scheduled event entry in SQLite.
- **Scheduled Events List (`/event_schedule_list`):**
  - Displays all scheduled repost entries stored in SQLite with their IDs, active recurring days, specific dates, and direct clickable `/event_schedule_invoke <ID>` commands for instant posting.

---

## 3. Directory Structure

```text
GdG-Event-Bot/
├── bot/
│   ├── __init__.py
│   ├── state.py          # Runtime state: pause flag + last published recap (runtime_state)
│   ├── keyboards.py      # Telegram inline keyboard layouts (+ SCHEDULE_DAYS)
│   ├── common/           # Helpers shared by every bot package
│   │   ├── auth.py       # admin_only decorator, is_admin_chat, describe_user
│   │   ├── messages.py   # resolve_message, command parsing, HTML fallback, reply fallback, chunked replies
│   │   ├── media.py      # Photo/document download helpers
│   │   ├── parsing.py    # Seat parsing, event keyword filter, event-ID extraction from replies
│   │   └── previews.py   # Admin approval card sending, warning blocks, Gemini quota alert
│   ├── handlers/         # Telegram command & message handlers (registered in main.py)
│   │   ├── control.py    # /bot_pause, /bot_resume, /bot_status
│   │   ├── public.py     # /start, /event_next, /event_subs
│   │   ├── ingestion.py  # Channel interception (process_message) and /event_process (/ep)
│   │   ├── albums.py     # Media-group (album) buffering for channel posts and admin uploads
│   │   ├── extraction.py # handle_event_extraction: AI parse -> pending event -> admin approval card
│   │   ├── edit.py       # /event_edit_* (EDIT_COMMAND_FIELDS / FIELD_EDITORS)
│   │   ├── subscribers.py # /event_sub_add, /event_sub_remove, ForceReply add-subscriber prompt
│   │   ├── recap.py      # /recap_generate and discussion-group forward handling
│   │   ├── repost.py     # /event_repost, /event_schedule_invoke
│   │   └── repost_schedule.py # /event_schedule, /event_schedule_update, /event_schedule_list
│   ├── callbacks/        # Inline button (CallbackQuery) handlers
│   │   ├── router.py     # handle_callback_query + CALLBACK_ROUTES prefix table
│   │   ├── events.py     # Publish / discard / cancel / reactivate event cards
│   │   ├── notices.py    # Cancellation / reactivation notices to the discussion group
│   │   ├── recap.py      # Publish / discard recap, WordPress draft & publish
│   │   ├── booking.py    # ➕ Prenota / 🚫 Esauriti / ➖ Annulla
│   │   ├── subscribers.py # 👥 Gestisci Iscritti panel (± seats, add prompt, close)
│   │   └── schedule.py   # Repost schedule weekday toggles, delete, close
│   ├── service/          # Telegram side effects shared by handlers and callbacks
│   │   ├── posts.py      # update_event_messages: sync channel post + discussion reply (with RetryAfter retry)
│   │   ├── booking.py    # Seat booking/unbooking flows and same-day conflict warnings
│   │   ├── notices.py    # send_admin_action_notice, send_discussion_notice
│   │   └── mentions.py   # User/subscriber mention formatting
│   └── event_generator/  # /event_generate (/eg)
│       ├── command.py    # Telegram command handler
│       ├── pipeline.py   # Generation pipeline, caption limit, admin preview
│       ├── ai.py         # Gemini prompt + response normalization
│       └── bgg.py        # BoardGameGeek search and cover download
├── core/
│   ├── __init__.py
│   ├── config.py         # Loads environment variables (.env), paths, constants
│   ├── ai_parser.py      # Gemini: generate_text, event extraction (+ seat safety net), WP article writing
│   ├── log_utils.py      # Daily rotating log handler and monthly log zip archiving
│   ├── instagram.py      # Meta Graph API: container creation & story publishing
│   ├── db/               # SQLite data access (public API: `from core.db import ...`)
│   │   ├── connection.py # get_connection, transaction(), fetch_one/fetch_all/execute, @db_safe
│   │   ├── schema.py     # CREATE TABLEs + COLUMN_MIGRATIONS applied by init_db()
│   │   ├── events.py     # events table: insert/update/delete, lookups, recap & upcoming queries
│   │   ├── reservations.py # reservation lookups, identity normalization, same-day conflicts
│   │   ├── seats.py      # Booking rules: book/unbook, admin seat ± and subscriber add/remove
│   │   └── scheduled.py  # scheduled_events (repost templates)
│   ├── scheduler/        # APScheduler jobs
│   │   ├── runner.py     # start_scheduler / stop_scheduler (job timetable)
│   │   ├── recap.py      # 16:00 daily recap card for admin approval
│   │   ├── archive.py    # 23:59 image archiving + booking shutdown, 00:05 monthly log zips
│   │   └── reposts.py    # 10:00 digest of scheduled reposts due today
│   └── wordpress/        # WordPress REST API (public API: `from core.wordpress import ...`)
│       ├── client.py     # Credentials, auth headers, wp_get / wp_post (with timeouts)
│       ├── categories.py # WP_POST_CATEGORY / slug / name -> category IDs
│       └── content.py    # upload_media, publish_article (draft), update_article_status
├── utils/
│   ├── __init__.py
│   ├── date_utils.py     # Date parsing, format validation (DD-MM-YYYY [HH:MM]), and anomaly checks
│   ├── image_utils.py    # Pillow image manipulation: collages, story generation, date folder resolution
│   └── templates.py      # Standardized Telegram message templates (stories, channel posts, recaps)
├── scripts/              # Utility and maintenance scripts
│   ├── generate_story.py # Utility script to manually generate Instagram Stories by event ID
│   ├── fix_event_keyboards.py # Utility script to synchronize event inline buttons with SQLite IDs
│   ├── clean_db.py       # Utility script to wipe database tables and clean image folders
│   ├── unzip_images.py   # Utility script to extract archived images by directory or date range
│   └── test_ig.py        # Diagnostic script to test Meta Graph API tokens
├── tests/                # unittest/pytest suite (mocks Telegram, uses temporary SQLite DBs)
├── data/                 # Default local storage for SQLite DB, fonts, and images
│   ├── Roboto-Bold.ttf
│   ├── Roboto-Regular.ttf
│   └── bot_database.db
├── .env         # Environment configuration (secrets, tokens, IDs) - GIT IGNORED
├── .gitignore            # Git rules ignoring .env, __pycache__, and data contents
├── requirements.txt      # Python dependencies
├── main.py               # Application entry point
├── README.md             # User and operator manual
└── GEMINI.md             # This document (technical and architectural specification)
```


### 3.1. `bot/` Package Architecture
- **Layering:** `handlers/` and `callbacks/` are the Telegram entry points. Both use `service/` for side effects shared across features (refreshing event posts, booking flows, discussion-group notices). Every layer uses `common/` helpers and `keyboards.py`. `event_generator/` is a self-contained feature package. Dependencies point one way (entry points → service → common), and no package imports `handlers/` or `callbacks/`. The one exception is shared runtime state, which lives in `bot/state.py`.
- **Package `__init__.py` files are empty.** Import from the specific module (e.g. `from bot.handlers.edit import event_edit_command`). Re-exporting would create two paths to the same function and make test patches silently miss.
- **Configuration is read at call time** through `from core import config` / `config.ADMIN_CHAT_ID` (also `PUBLIC_CHANNEL_ID`, `DISCUSSION_GROUP_ID`, `ALLOW_GROUP_EVENT_NEXT`, `DATA_DIR`, `TELEGRAM_BOT_USERNAME`). Tests patch these once at `core.config.*` (see §3.2). Patch functions where they are *used*, e.g. `bot.handlers.extraction.parse_event_message` or `bot.callbacks.events.update_event_messages`.
- **`bot/common/`:**
  - `auth.py`: `@admin_only()` / `@admin_only(notify=True)` restricts a handler to `ADMIN_CHAT_ID` (`notify=True` replies `Non sei autorizzato.` to outsiders). Also `is_admin_chat`, and `describe_user(user, role="Admin")` for the `Admin <id> (@username)` identifier in audit logs. Do not hand-write chat-ID checks in new admin commands.
  - `messages.py`: `resolve_message`, `command_argument` / `command_tokens`, `truncate_caption` / `CAPTION_LIMIT`, `with_html_fallback(call)` (send with `parse_mode="HTML"`, retry as plain text), `send_with_reply_fallback` (reply in the discussion group, fall back to a plain send if the reply target is gone), `reply_in_chunks`, `send_image_or_error`, `private_chat_link`, `is_not_modified_error`.
  - `media.py`: `download_media_bytes`, `download_first_image` (largest photo, then image document), `read_image_file`.
  - `parsing.py`: `parse_seats_input(value)`, the single seat parser for `/event_edit_seats` and the `SEATS` argument of `/event_repost` / `/event_schedule_invoke`. It returns `None` for unlimited (`null`, `nessuno`, `illimitati`, `unlimited`, `none`, `0`, empty), `(free, total)` for `X/Y`, or `(None, total)` for a bare integer. Unlimited events display `UNLIMITED_SEATS_DISPLAY = "no limit"`, the same string the AI parser outputs. Also here: `contains_event_keywords` / `EVENT_KEYWORD_PATTERNS` (the pre-AI keyword filter) and `extract_event_id_from_reply`.
  - `previews.py`: `send_admin_preview` (approval card as photo caption or text), `build_admin_warning_block` / `date_anomaly_warning`, and `notify_quota_depleted`, the Gemini credit alert used by extraction, recap WordPress generation and `/event_generate`.
- **`bot/state.py`:** `runtime_state` (`BotRuntimeState`) holds the pause flag (`is_paused`) and the last published recap (`last_recap_message_id`, `last_recap_events`). `bot/callbacks/recap.py` records a published recap via `remember_published_recap(message_id, events)`; `bot/handlers/recap.py` reads it when the recap is auto-forwarded into the discussion group.
- **`bot/handlers/`:**
  - `albums.py` owns `media_groups` / `admin_media_groups`, module-level dicts (changed in place, never reassigned) that buffer album photos for channel ingestion and for admin `/ep` / `/event_edit_image`.
  - `extraction.handle_event_extraction` is the single ingestion pipeline. Channel posts, albums, `/ep`, `/event_repost` and `/event_schedule_invoke` all go through it.
  - **`/event_edit_*` dispatch (`edit.py`):** `EDIT_COMMAND_FIELDS` maps each command to a DB field. `FIELD_EDITORS` maps fields that need custom logic (`image_path`, `date`, `seats`, `booked_seats`, `extra_info`, `is_roleplay`) to editor coroutines `(update, event_id, current_event, value) -> bool`; other fields are written verbatim. Editors raise `EditInputError(reply, parse_mode)` for invalid input. To add an editable field, add one entry to `EDIT_COMMAND_FIELDS` (plus a `FIELD_EDITORS` entry if it needs parsing) and register the command in `main.py`.
  - Shared flows: `subscribers._add_subscriber_and_notify` (used by the ForceReply prompt and `/event_sub_add`), `subscribers._parse_subscriber_command` (shared by `/event_sub_add` and `/event_sub_remove`), `public._reply_with_participants` (used by `/event_subs` and the `start=subs_<id>` deep link), and `repost.extract_repost_content` (shared by repost and repost scheduling).
- **`bot/callbacks/`:** `router.handle_callback_query` is the only `CallbackQueryHandler` registered in `main.py`. It walks `CALLBACK_ROUTES`, an ordered `(prefix, handler)` table, and calls `handler(query, context, payload)` with the callback data that follows the prefix. To add a button, give it a new callback prefix (one that is not a prefix of an existing entry; a test enforces this), write the handler in the matching feature module, and add one row to `CALLBACK_ROUTES`.
- **`bot/service/`:**
  - `posts.update_event_messages` re-renders an event's channel post (edit caption/text, switching kind only on Telegram's "no caption/text" error) and its discussion-group booking reply, retrying on `RetryAfter`.
  - `booking.py` handles seat booking/unbooking and same-day conflict warnings.
  - `notices.py` provides `send_admin_action_notice` and `send_discussion_notice`.
  - `mentions.format_subscriber_tag` is the single tag formatter for stored reservations (`@username`, `tg://user` link, or name).


### 3.2. `core/` Package Architecture
- **Configuration is read at call time** (`config.ADMIN_CHAT_ID`, `config.DB_PATH`, `config.WP_URL`, `config.IG_ACCESS_TOKEN`, …), never copied at import. Tests and scripts redirect the database by setting/patching `core.config.DB_PATH`.
- **`core.db` and `core.wordpress` are facades.** Their `__init__.py` re-exports the public API (`__all__`), so callers write `from core.db import get_event`. The submodules call each other directly, so patch a DB/WordPress function in the module that *uses* it. HTTP for WordPress goes through `core.wordpress.client` (patch `core.wordpress.client.requests.*`). `core.scheduler` is a set of job modules with an empty `__init__.py`, the same as the `bot/` packages: import `core.scheduler.runner.start_scheduler`, `core.scheduler.recap.generate_daily_recap`, etc.
- **DB plumbing (`core/db/connection.py`):**
  - `transaction()` yields a cursor with dict-like rows, commits or rolls back, and always closes the connection.
  - `fetch_one` / `fetch_all` / `execute` / `execute_many` wrap single statements.
  - `@db_safe(default)` logs `DB error in <function>: …` and returns `default` (`default=list` gives a fresh `[]`), so callers keep the old "never raises" contract.
  - `get_connection()` returns a raw connection for scripts.
  - SQL string literals use single quotes (`status IN ('approved', 'cancelled')`); double quotes are reserved for identifiers.
- **Schema changes:** add the column to the `CREATE TABLE` in `core/db/schema.py` *and* to `COLUMN_MIGRATIONS`, so existing databases get an `ALTER TABLE` on the next start.
- **Seat bookkeeping (`core/db/seats.py`):** every reservation change runs in one transaction with `_load_seat_state` (event exists / not cancelled / capacity) and `_set_booked_seats`, which rewrites both `booked_seats` and the `free/max` `seats` string. `normalize_identity` applies the legacy rule "a username with spaces is a full name".
- **Dates:** pure date helpers live in `utils/date_utils.py` (`parse_date_tuple_from_str`, `event_date_tuple`, `are_events_on_same_day`); `core.db` only queries.
- **Gemini (`core/ai_parser.py`):** `generate_text(prompt)` is the single entry point to `config.GEMINI_MODEL` and raises `GeminiQuotaError` on quota/credit errors. `strip_json_fence` and `coerce_bool` are shared with `bot/event_generator/ai.py`.
- **External HTTP:** WordPress calls default to a 30 s timeout (category lookups 10 s). Instagram Graph calls run in a worker thread (`asyncio.to_thread`) with a 30 s timeout, so a slow Meta API cannot freeze the bot.
- **Known layering debt:** `core/scheduler/recap.py` still imports `bot.keyboards.get_recap_approval_keyboard` (core → bot). Moving the recap job into `bot/` would remove it.

---

## 4. Database Schema (SQLite: `bot_database.db`)

### Table: `events`
| Column | Type | Constraints / Default | Description |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Unique event identifier |
| `title` | TEXT | | Event / Game title |
| `date` | TEXT | | Raw extracted Italian date string |
| `normalized_date` | TEXT | | Standardized date string (`DD-MM-YYYY`) |
| `system` | TEXT | | Game system / genre |
| `host` | TEXT | | Master / Host handle or name |
| `seats` | TEXT | | Display string (e.g. `3/3` or `0/0 Completo`) |
| `booked_seats` | INTEGER | DEFAULT 0 | Count of currently reserved seats |
| `max_seats` | INTEGER | | Maximum capacity (NULL if unlimited) |
| `description` | TEXT | | Event synopsis / description |
| `extra_info` | TEXT | | Extra metadata (difficulty, warnings, format, tags) |
| `original_text` | TEXT | | Raw Telegram message text |
| `image_path` | TEXT | | Absolute or relative local path to original image |
| `status` | TEXT | | `pending`, `approved`, `discarded`, `cancelled` |
| `is_recap` | INTEGER | DEFAULT 0 | Historical flag (recaps now filter by date) |
| `message_link` | TEXT | | Link to message in public channel |
| `telegram_message_id`| INTEGER | | Telegram Message ID of published event post |
| `wp_post_id` | INTEGER | | Associated WordPress post ID |
| `wp_post_url` | TEXT | | Associated WordPress post edit/view URL |
| `is_roleplay` | INTEGER | DEFAULT 0 | 1 if roleplaying event (Master), 0 if non-RPG (Host) |

### Table: `reservations`
| Column | Type | Constraints / Default | Description |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Unique reservation ID |
| `event_id` | INTEGER | | Foreign key referencing `events(id)` |
| `user_id` | INTEGER | | Telegram User ID of participant |
| `username` | TEXT | | Telegram username (without @) or null if user has no handle |
| `full_name` | TEXT | | Display / full name for users without a username |
| `seats_booked` | INTEGER | DEFAULT 0 | Number of seats booked by this user |

### Table: `scheduled_events`
| Column | Type | Constraints / Default | Description |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Unique scheduled event identifier |
| `title` | TEXT | | Event / Game title |
| `text` | TEXT | | Raw event text template |
| `image_path` | TEXT | | Path to stored image for the scheduled event |
| `schedule_days` | TEXT | DEFAULT '[]' | JSON array of active weekdays for recurring reposting |
| `specific_date` | TEXT | | Optional specific date and time (`DD-MM-YYYY [HH:MM]`) |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | Creation timestamp |

---

## 5. Environment Variables (`.env`)

| Variable | Description | Example / Format |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Token provided by `@BotFather` | `123456789:ABCdef...` |
| `PUBLIC_CHANNEL_ID` | Telegram Channel ID | `-1001234567890` |
| `ADMIN_CHAT_ID` | Admin User ID or Admin Group ID | `123456789` or `-100...` |
| `GEMINI_API_KEY` | Google AI Studio API Key | `AIzaSy...` |
| `GEMINI_MODEL` | Gemini model name | `gemini-3.1-flash-lite` |
| `WP_URL` | WordPress base URL | `https://www.gildadelgrifonetorino.it` |
| `WP_USERNAME` | WordPress username | `direttivogilda` |
| `WP_APP_PASSWORD` | WordPress Application Password | `xxxx xxxx xxxx xxxx` |
| `WP_POST_CATEGORY` | (Optional) Category ID or name for generated posts | `12` or `Eventi` |
| `IG_ACCESS_TOKEN` | Meta Long-Lived Graph API User Access Token | `EAA...` |
| `IG_ACCOUNT_ID` | Instagram Business Account Numeric ID | `178414...` |
| `DATA_DIR` | (Optional) Custom path for storage | `/var/gdg_data` |
| `MAX_EVENTS_PER_ROW` | (Optional) Maximum number of event images per row in collages | `4` |
| `ALLOW_GROUP_EVENT_NEXT` | (Optional) Enable/disable `/event_next` in discussion group (`true`/`false`) | `true` |

---

## 6. Templates & Character Limit Handling
Defined in `utils/templates.py`:
- **`format_event_title_link(event)`:** Centralized title formatter ensuring all event titles across notifications and lists are HTML escaped and bolded (`<b>{escaped_title}</b>`), and hyperlinked to the event's public channel message (`<a href="{link}"><b>{escaped_title}</b></a>`) whenever a link exists.
- **Instagram Story Text:** Standardized Italian text block.
- **Public Event Post:** Standardized channel post with emoji formatting.
- **Full Recap Template (`recap_generate_text`):** Header + Event list with bold titles + Footer.
- **Recap Discussion Comment (`recap_links_text`):** Header + list of active events with bold hyperlinked titles to channel posts.
- **Slim Recap Template:** Automatically activated if the full recap exceeds Telegram's 1024-character caption limit. Has minimal fixed headers/footers.
- **Repost Schedule Card (`format_schedule_repost_message`):** Management card for a `scheduled_events` row (active weekdays, specific date, `/event_schedule` usage). Shared by `/event_schedule` and the weekday toggle callbacks.

---

## 7. Instagram Story Publishing Status & Unpause Guide

### Current Status
- Story canvas generation with Pillow is **active and functional** (1080x1920 with top image, wrapped titles/systems, seat badges, and footer).
- Instagram publishing is disabled while Meta developer page linking is established. The bot sends the generated story image to `ADMIN_CHAT_ID` for preview instead (`_send_story_preview` in `bot/callbacks/events.py` for events, `_run_post_recap_pipeline` in `bot/callbacks/recap.py` for recaps).

### Steps to Re-enable Meta Graph API Publishing:
1. Ensure the Instagram account is converted to a Professional/Business account.
2. Link the Instagram account to a Facebook Page managed by the same account.
3. In [Meta Graph API Explorer](https://developers.facebook.com/tools/explorer/):
   - Select App -> Get User Access Token.
   - Permissions: `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`.
   - Grant access to the linked Page and IG Account.
   - Run `me/accounts?fields=instagram_business_account` to get numeric `IG_ACCOUNT_ID`.
   - Extend token in [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/) to get 60-day `IG_ACCESS_TOKEN`.
4. Update `.env` with `IG_ACCESS_TOKEN` and `IG_ACCOUNT_ID`.
5. Call `core.instagram.publish_instagram_story()` (after a temporary WordPress media upload for a public image URL) from `_send_story_preview` in `bot/callbacks/events.py` and from `_run_post_recap_pipeline` in `bot/callbacks/recap.py`.
