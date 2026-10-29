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
  - [2.7. Post-Recap Article & Story Pipeline (`bot/callbacks/recap.py`)](#27-post-recap-article--story-pipeline-botcallbacksrecappy)
  - [2.8. Nightly Image Archiving (`core/scheduler/archive.py` & `unzip_images.py`)](#28-nightly-image-archiving-coreschedulerarchivepy--unzip_imagespy)
  - [2.9. Daily Log Rotation & Monthly Log Archiving (`core/log_utils.py` & `core/scheduler/archive.py`)](#29-daily-log-rotation--monthly-log-archiving-corelog_utilspy--coreschedulerarchivepy)
  - [2.10. Event Reposting & Repost Scheduling (`bot/handlers/repost*.py` & `core/scheduler/reposts.py`)](#210-event-reposting--repost-scheduling-bothandlersrepostpy--coreschedulerrepostspy)
  - [2.11. Eventbrite Integration (`core/eventbrite/` & `bot/service/eventbrite*.py`)](#211-eventbrite-integration-coreeventbrite--botserviceeventbritepy)
- [3. Directory Structure](#3-directory-structure)
  - [3.1. `bot/` Package Architecture](#31-bot-package-architecture)
  - [3.2. `core/` Package Architecture](#32-core-package-architecture)
  - [3.3. `tests/` Layout](#33-tests-layout)
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
- Compiles daily recap messages and multi-image collages on game days (default Mon, Wed, Fri, Sat, Sun; `RECAP_WEEKDAYS`).
- Generates Instagram Story images (1080x1920) for both individual events and daily recaps using Pillow.
- Generates engaging recap articles using Gemini AI and drafts/publishes them on the Astro website (Markdown file on a GitHub draft branch, images on Cloudflare R2) or, with `ARTICLE_BACKEND=wordpress`, on WordPress via the REST API.

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
3. **AI Event Generation (`/event_generate`):**
   - Admins can send `/event_generate <istruzioni>` (or reply to a message with the command) in `ADMIN_CHAT_ID`.
   - Handled in the `bot/event_generator/` package (`command.py` → `pipeline.py`, using `ai.py` and `bgg.py`):
     - Gemini AI interprets natural language instructions (games, date, host, seats, extra info, RPG vs board game) and writes an engaging synopsis/pitch in Italian constrained to <= 400 characters.
     - For each identified game, `fetch_bgg_game_image` looks for the box cover: with `BGG_API_TOKEN` set it queries the BoardGameGeek JSON API (`https://api.geekdo.com/api/geekitems`, Bearer token) and takes the best match; without a token, or when BGG answers with an error (e.g. 401) or finds nothing, it first tries the BGG ID Gemini guessed in the event JSON (`bgg_ids`) through the tokenless item-detail endpoint (`fetch_bgg_image_by_id`, used only if `bgg_item_matches` finds the game among BGG's name and alternate names). Then it falls back (`fetch_fallback_game_image`) to Wikidata items that have a BoardGameGeek ID (P2339), taking the BGG box art for their P2339 ID (same check), else the lead image of their en/it Wikipedia article or their Commons image; then to a Wikipedia search that only accepts pages named after the game and described as a game; and last to a Bing image search whose results must mention the game and are each confirmed by Gemini vision (`image_matches_game`, any error counts as no) — no image is better than a wrong one.
     - If multiple games were requested, builds a uniform horizontal collage via `utils/image_utils.create_collage_from_bytes`. If a single game was requested, preserves the single image without collaging.
     - Programmatically guarantees the entire formatted event caption stays within Telegram's 1024-character caption limit via `enforce_caption_limit()`.
     - Inserts the generated event as `pending` into SQLite and sends the preview card to `ADMIN_CHAT_ID` with standard approval buttons (`[Publish]`, `[Discard]`, `[👥 Gestisci Iscritti]`).
4. **Monitoring Pause / Resume (`/bot_pause`, `/bot_resume`, `/bot_status`):**
   - Admins can send `/bot_pause` in `ADMIN_CHAT_ID` to make the bot temporarily "blind" to `PUBLIC_CHANNEL_ID` (it will not intercept, parse, or delete messages from the channel).
   - Send `/bot_resume` to re-enable interception, and `/bot_status` to check the current operational state (including the Eventbrite-only mode below).
   - `/bot_eventbrite_only_toggle` flips `runtime_state.eventbrite_only` (initial value `EVENTBRITE_ONLY_MODE`, in memory, needs Eventbrite configured). **ON:** the pending card (`get_approval_keyboard`) shows `[Discard]` and `[🚀 Telegram + EB] [🎟️ Solo Eventbrite]` (no plain Publish) and `_publish` no longer generates the automatic Instagram story preview. **OFF:** classic card, `[Publish] [Discard]` + `[🚀 Publish + Eventbrite]`. `[🎟️ Solo Eventbrite]` (`publish_eb_only_<id>`) approves with **no channel post**; `[🚀 Telegram + EB]` still posts. Rule behind it: `send_discussion_notice` sends nothing for an event with no `telegram_message_id`, so Eventbrite-only events produce no discussion-group traffic (cancellations, admin-action notices); their Eventbrite booking announcements go to the admin chat instead. Only cards created after a toggle follow it. An Eventbrite-only event cannot be booked on Telegram.

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
- **[Cancel]:** (after the confirmation step of §2.6) Updates DB status to `cancelled`, updates message to `⚠️ ANNULLATO`, switches keyboard to `[♻️ Riattiva Evento]` and `[👥 Gestisci Iscritti]`, and posts a notice to `DISCUSSION_GROUP_ID` tagging all subscribers.
- **[Publish]:**
  1. Generates 1080x1920 Instagram Story image using `utils/image_utils.create_story_image()` and saves it in `[DATA_DIR]/YYYY/MM/DD/`.
  2. Sends the generated story image to `ADMIN_CHAT_ID` for review *(Meta Graph API publishing is currently commented out for testing; see section 6)*.
  3. Formats the official standardized public channel post using `utils/templates/event.py` (`format_public_event_message`).
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
  - Opens a 1-on-1 private chat with the bot and executes `/start event_next`, which triggers `/event_next` and displays all today's and upcoming scheduled events directly in DM. `/event_next <date>` (typed as the command itself, never through the deep link) lists only one day, parsed by `utils.date_utils.parse_day_filter` (`dd-mm-yyyy`, `oggi`, weekday names = next such day counting today; invalid or past dates get an explanatory reply). Each event in the `/event_next` listing includes direct deep links (`start=subs_{id}`) and clickable `/event_subs {id}` commands for instantaneous roster access.

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
  - Admins can click Cancel on any event. The button only asks for confirmation: it swaps the card buttons for `[✅ Sì, annulla]` (`cancel_confirm_<id>`) and `[↩️ Indietro]` (`cancel_abort_<id>`), with no popup. Nothing changes until the confirmation; a repeated confirmation is ignored.
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
4. **Text Formatting (`utils/templates/recap.py`: `recap_generate_text` & `recap_links_text`):**
   - Italian day names (Lunedì, Mercoledì, etc.).
   - Lists events in caption with bold titles and live available seats: `- <b>Titolo</b> (Sistema) : X/Y` (or `- ❌ <b>Titolo</b> (Sistema) : X/Y [ANNULLATO]`).
   - Generates comment text `recap_links_text` listing all active events with bold hyperlinked titles: `- <a href="..."><b>Titolo</b></a> (Sistema)`.
   - If recap caption length exceeds Telegram's 1024-character caption limit, automatically falls back to slim recap format.
5. **Approval:**
   - Sends collage + recap text to `ADMIN_CHAT_ID` with `[Publish Recap]` and `[Discard Recap]`.

### 2.7. Post-Recap Article & Story Pipeline (`bot/callbacks/recap.py`)
When `[Publish Recap]` is clicked:
1. **Public Telegram Recap:** The collage + text is published to `PUBLIC_CHANNEL_ID`. The links message (`recap_links_text`) is NOT posted to the public channel; it is sent exclusively as a reply to the automatic channel forward in the Discussion Chat group (`DISCUSSION_GROUP_ID`).
2. **Instagram Recap Story:**
   - `utils/image_utils.create_recap_story_image()` builds a 1080x1920 canvas.
   - Collage pinned at top, header `Proposte del [Data]`, bulleted event list with seats, and footer:
     `Ci vediamo alle {EVENT_START_TIME}, alla {ASSOCIATION_ADDRESS}!` (default: `Ci vediamo alle 20:45, alla Gilda del Grifone, Via Ada Negri 8/A, Torino!`)
   - Sent to `ADMIN_CHAT_ID` for review.
3. **Article Generation (`_create_article_draft`, backend chosen by `ARTICLE_BACKEND`, default `astro`):**
   - **`astro`** (`core/astro/` & `generate_astro_article`): uploads each event image and the collage to R2 under `serate/<slug>/` (JPEG/PNG resized to max 1600px wide), asks Gemini for a Markdown body, builds the front matter (`title`, `date`, `cover`, `excerpt`, `tavoli` with `gioco`/`tipo`/`immagine`) and commits `ASTRO_CONTENT_DIR/<YYYY-MM-DD>-<slug>.md` on a new branch `serata/<slug>` (slug: `eventi-della-serata-<giorno>-<dd-mm-yyyy>`). Stores `article_backend='astro'`, `article_ref` (branch) and `wp_post_url` (draft link), then sends the draft link with `[Pubblica sul sito]` (`publish_astro_<dd-mm-yyyy>`).
   - **`wordpress`** (`core/wordpress/` & `generate_wordpress_article`): uploads each event image to the WordPress Media Library (style set to max 400x400px), the collage as `featured_media`, and creates a `draft` post. Updates `wp_post_id` and `wp_post_url`, then sends the editor link with `[Pubblica su WordPress]` (`publish_wp_<post_id>`).
   - Gemini receives event details, links and image URLs to write the article in Italian (HTML for WordPress, Markdown for Astro; shared instructions in `_article_brief`).
4. **One-Click Publish:**
   - `[Pubblica sul sito]` looks the branch up by date (`get_article_ref_for_date`), merges it into `ASTRO_GITHUB_BRANCH` and deletes it; Cloudflare deploys the site (~1-2 min) and the bot shows the public URL.
   - `[Pubblica su WordPress]` changes post status from `draft` to `publish` via REST API.

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
  - Line 3: `[➖] [⏳ Anticipo: N gg] [➕]` sets `advance_days` (0-30, `sched_adv_{id}_{inc|dec|noop}`, `bot.callbacks.schedule.handle_advance_days`).
  - Admins can also specify a one-off scheduled date via `/event_schedule [ID] [DD-MM-YYYY [HH:MM]] [N]`; the optional trailing integer `N` is `advance_days` (split off by `_split_advance`; `/event_schedule 5 2` changes only N, rejected outside 0-30).
- **Scheduled Repost Notification & Invocation (9:00 AM Cron):**
  - Runs daily at **9:00 AM** via APScheduler.
  - Queries `scheduled_events` with `core.db.get_scheduled_events_due(today)`: a template is due when its weekday / `specific_date` matches `today + advance_days` (`advance_days = 0` is the original same-day behaviour). Each entry shows the event date and an invoke command carrying it (`/event_schedule_invoke ID DD-MM-YYYY [HH:MM]`).
  - Sends a consolidated digest to `ADMIN_CHAT_ID` listing each scheduled event with a clickable invocation command: `/event_schedule_invoke <SCHEDULED_ID>`.
  - Invoking `/event_schedule_invoke <SCHEDULED_ID> [DATE] [SEATS]` prepares the event and outputs the approval card ready for publishing. An explicit date wins (the template's `HH:MM` is added when missing). Without one the date is today, or, when `advance_days > 0`, the template's nearest occurrence on or after today (`core.db.next_scheduled_occurrence`), so invoking on the event day itself gives today.
- **Scheduled Content Overwrite (`/event_schedule_update <SCHEDULED_ID>`):**
  - Admins can reply to any new event post with `/event_schedule_update <SCHEDULED_ID>` to overwrite the text and image template of an existing scheduled event entry in SQLite.
- **Scheduled Events List (`/event_schedule_list`):**
  - Displays all scheduled repost entries stored in SQLite with their IDs, active recurring days, specific dates, and direct clickable `/event_schedule_invoke <ID>` commands for instant posting.

### 2.11. Eventbrite Integration (`core/eventbrite/` & `bot/service/eventbrite*.py`)
Optional. An approved event can also be published on **Eventbrite** so people outside Telegram can book. Both platforms draw from **one seat pool**. The integration is enabled only when `EVENTBRITE_TOKEN`, `EVENTBRITE_ORGANIZATION_ID` and `EVENTBRITE_VENUE_ID` are all set (`core.eventbrite.eventbrite_enabled()`); every button and hook checks it, so with Eventbrite unconfigured the bot behaves exactly as before and no new buttons appear. There are no webhooks and no web server: Eventbrite is polled.

**Seat model.** `eb_seats` is the sum of `seats_booked` over the event's reservation rows with `source='eventbrite'`; `telegram_booked = booked_seats - eb_seats`; `capacity` is `max_seats` (or `EVENTBRITE_UNLIMITED_CAPACITY` when `max_seats` is NULL). The single free ticket class gets `quantity_total = max(eb_seats, capacity - telegram_booked)`, so Eventbrite's *quantity minus sold* always equals the seats still free on Telegram. When no seat is left (`quantity <= eb_seats`) `core.eventbrite.tickets.update_ticket_capacity` closes sales instead of sending the total: Eventbrite rejects `quantity_total=0` (`NO_QUANTITY_TOTAL`) and a `sales_end` in the past (verified), so the total stays at the sold count (Eventbrite shows "Sold out"), `sales_end` is set 2 minutes ahead and, with nothing sold, the ticket class is also `hidden`. Seats freeing up push the total back with `hidden=false` and `sales_end` at the event end. A stored `eventbrite_quantity_total` of 0 therefore means "sales closed, nothing sold". A cancelled event gets `quantity_total = eb_seats`, which closes sales. The last pushed value is cached in `events.eventbrite_quantity_total` to skip no-op calls (`core.eventbrite.payload.ticket_quantity`).

**Publishing** (`bot.service.eventbrite.publish_event_to_eventbrite`, shared by `[🚀 Publish + Eventbrite]` / `[🚀 Telegram + EB]` (`publish_eb_event_<id>`), `[🎟️ Solo Eventbrite]` (`publish_eb_only_<id>`, approves with no channel post), `[🎟️ Pubblica su Eventbrite]` (`eb_publish_<id>`) and `/event_publish_eventbrite [ID]`):
1. Refuses (messaging `admin_chat_id`) when the integration is off, the event is missing or not `approved`, the date is missing/past. Nothing is created on Eventbrite in these cases. An event with nothing left to sell (`0/0 Completo`, or fully booked on Telegram) is **not** refused: it is published sold out, with a 1-seat ticket class created `closed=True` (hidden, `sales_end` 2 minutes ahead, so it can never be bought) and `eventbrite_quantity_total = 0`; the success notice adds the sold-out line, and the first sync with a free seat reopens it (see the seat model). `max_seats` NULL (unlimited) is never full.
2. Idempotent: an already `live` event just replies with its link; a `draft` resumes from the failed step. Steps run in `asyncio.to_thread` and store ids after each one: create event → create ticket class → upload logo (a failure is only a warning with a `[🖼️ Riprova caricamento logo]` button (`eb_logo_<id>`, `retry_logo_on_eventbrite`), the event still goes live; the image is padded to 2:1 by `utils.image_utils.pad_to_aspect`; the upload to the pre-signed URL goes out with a browser User-Agent and the whole upload cycle is retried up to 3 times with a fresh upload target on 429/502/503/504 and network errors, honouring `Retry-After` up to 15 s, because Eventbrite's WAF sometimes answers it with an HTML "Whoops!" page; errors are reduced to a one-line reason) → write the description page (structured content, version = stored version + 1) → publish. `eventbrite_status` goes `draft` → `live`.
3. Sends `✅ Evento pubblicato su Eventbrite: <url>`, swaps the admin card buttons through `events.admin_message_id` (so the button and the command behave the same) and calls `update_event_messages`, so the discussion reply gains the link.
- The link appears **only** in the discussion-group booking message (`utils.templates.event.format_discussion_booking_message`); the channel post is unchanged.

**Background publish.** The buttons and `/event_publish_eventbrite` (and `[🎟️ Ricrea su Eventbrite]`) call `start_eventbrite_publish`, which runs `publish_event_to_eventbrite` / `recreate_on_eventbrite` as an `asyncio` task and returns at once (tasks kept in `runtime_state.eventbrite_tasks`, event ids in flight in `runtime_state.eventbrite_publishing`; a second press for the same event gets `⏳ Pubblicazione su Eventbrite già in corso`). Reason: the Application handles updates one at a time, so awaiting ~10 Eventbrite calls inside the callback held back the channel post's auto-forward in the discussion group, i.e. the booking message with its buttons. Now that message is sent as before Eventbrite existed, and `publish_event_to_eventbrite` ends with `update_event_messages`, which edits the stored `discussion_message_id` to add the Eventbrite link. `handle_discussion_forward` re-reads the event after sending and edits the message once if the publish finished in the meantime.

**Sync.** `bot.service.posts.update_event_messages` runs after every booking, unbooking, admin seat change and edit, and ends with `sync_eventbrite(context, event, content_changed, image_changed)`. It returns at once when Eventbrite is disabled, the event has no `eventbrite_event_id`, or `eventbrite_status` is `canceled`/`draft`. It pushes capacity (approved events only, when the quantity differs from the cached one), content (`update_event` + description page) when `eventbrite_content` is set, and the logo when `update_image` is set. `/event_edit_*` passes `eventbrite_content=True` for `title, date, system, host, extra_info, description, is_roleplay, seats` (`EVENTBRITE_CONTENT_FIELDS`; `seats` because the description shows `Posti totali: <max_seats>`, left out for unlimited and `0/0` events). Errors are logged and sent to the admins as `⚠️ Sync Eventbrite fallita per #id: …`; they never raise into the Telegram flow. A date edit that moves the event into the past skips the date fields and warns the admins. `/event_edit_booked` and `/event_edit_seats X/Y` refuse to go below `eventbrite_seat_count`. A failed logo upload during a sync (`/event_edit_image`) is reported on its own (`⚠️ Logo non aggiornato su Eventbrite …`) with the same retry button, after the capacity and content updates have already been pushed.

**Telegram booking vs Eventbrite.** `handle_seat_booking` books in the database, then `reserve_on_eventbrite` pushes the new `quantity_total` for a linked `live` event with limited seats and reads `quantity_sold` from that same response (the later sync then skips its push). If Eventbrite already sold more than we hold (`quantity_sold + Telegram seats > max_seats`, or a 400 rejecting a total below the sold count) the booking is undone (`unbook_seat`), `poll_event_now` pulls the orders in, the card is refreshed and the user gets an alert (`EVENTBRITE_TAKEN`). Any other failure (network, 5xx) keeps the booking: the poller's overbooking notice is the safety net.

**Booking poller** (`bot.service.eventbrite_poll.poll_eventbrite_bookings`, registered by `main.post_init` through `core.scheduler.runner.add_interval_job` every `EVENTBRITE_POLL_MINUTES`). For each `get_eventbrite_tracked_events()` row (linked, `approved`/`cancelled`, dated today or later, or yesterday) it fetches the Eventbrite event (1 call, with `expand=ticket_classes`) and sums `quantity_sold`. Only when that differs from the Eventbrite seats we have stored (`eventbrite_seat_count`), when the response has no ticket classes, or when a full check is due (`EVENTBRITE_FULL_SYNC_MINUTES`, default 30, `0` = every poll; last full fetch kept in memory per event) does it also fetch the active orders (attendees neither cancelled nor refunded), because the orders are only needed for the attendees' names. Verified on a real event: cancelling an order lowers `quantity_sold`, turns the order `refunded` and flags its attendee `cancelled` and `refunded`. A total that stays equal while the people change (one cancels, another books between two polls) is only caught by the periodic full check. If `quantity_sold` keeps disagreeing with the orders after a full fetch, that is logged once and the orders are fetched on every poll for that event until they agree. Then it:
- events already `canceled` on Eventbrite, and `draft` ones (a failed publish), are not polled (`get_eventbrite_tracked_events` skips them); an event **deleted by hand** (`NOT_FOUND` on the fetch, or on a sync) is unlinked by `unlink_deleted_eventbrite_event` (link cleared, one notice replying to the card, card refreshed, so an approved event offers `[🎟️ Pubblica su Eventbrite]` again), and resuming a deleted draft starts over once; and an `ALREADY_CANCELED` answer to a cancel call (event cancelled by hand) counts as cancelled, so it is never retried;
- records an Eventbrite-side cancellation (`✅ … annullato su Eventbrite` for a Telegram-cancelled event, `⚠️ … annullato su Eventbrite ma attivo su Telegram` otherwise);
- diffs the orders against `reservations(source='eventbrite')` and applies every change with `core.db.seats.apply_eventbrite_order` (no capacity check: the booking already happened; it returns `overbooked` when `booked > max_seats`);
- when something changed, calls `update_event_messages` (which also pushes the corrected capacity), announces each change in the discussion group, or, for an Eventbrite-only event (no `telegram_message_id`), in the admin chat as a reply to the admin card via `notify_admin(parse_mode="HTML")` (`🎟️ Mario R. ha prenotato 2 posti tramite Eventbrite per: …` / `❌ Mario R. ha liberato … (Eventbrite) per: …`, only while the event is `approved` and `EVENTBRITE_BOOKING_NOTIFICATIONS` is on) and alerts the admins on overbooking (naming the latest Telegram booker);
- for a Telegram-cancelled event in `closed` state with no active orders left, calls `finish_eventbrite_cancellation(..., from_poller=True)`, which completes the Eventbrite cancellation;
- on `EventbriteError` with `HIT_RATE_LIMIT` it stops the cycle; any other error only skips that event.
- **Rate budget:** about one Eventbrite call per tracked event per poll (the orders call only on a change or at the periodic full check). With 10 events every 2 minutes that is about 300 calls per hour plus ~20 for the full checks, under Eventbrite's limits of 2,000 calls/hour and 48,000/day per application (event creation/copy and publishing: 200/hour each).

**Setup** (`scripts/eventbrite_setup.py`): `--check --orgs` (token and `EVENTBRITE_ORGANIZATION_ID`), `--create-venue` (`EVENTBRITE_VENUE_ID`), optionally `--create-collection "NAME"` once per collection (ids for the two `EVENTBRITE_COLLECTION_*` settings; collections made by hand in the dashboard expose their id at the end of their URL, `/cc/name-<id>`). The API creates collections as drafts and cannot publish them: publish each from the dashboard. Restart the bot afterwards.

**Venues:** `eventbrite_venue_ids()` = `EVENTBRITE_VENUE_ID` (default) + `EVENTBRITE_VENUE_ID_ALTERNATIVES`. `/bot_eventbrite_venue` (admin) shows one button per venue (names via `GET /venues/{id}/`, cached in `runtime_state.venue_names`; current ✅, default tagged); the last row is `[❌ Chiudi]` (`ebvenue_close`, deletes the message); the callback `ebvenue_<id>` (`bot/callbacks/venues.py`) sets `runtime_state.eventbrite_venue` (in memory, validated against the configured ids). `_publish_blocking` stores the venue on the event (`events.eventbrite_venue_id`) **before** `create_event`, so syncs and a resumed draft keep it; `event_payload` sends `venue_id` only when the event has a stored venue, so events published before this feature keep whatever venue they have on Eventbrite and are never moved by a content sync, even if `EVENTBRITE_VENUE_ID` changes; the default only affects events published from then on. `clear_eventbrite_info` forgets it, so a recreate takes the current pick. The publish notice names the venue when several are configured. Venues are created/edited with `scripts/eventbrite_setup.py --create-venue` / `--update-venue` (the API cannot delete them; an update needs the whole address, the script merges it); the project skill `.claude/skills/eventbrite-venues` documents the workflow.

**Description:** `description_modules` builds one structured-content text module: `Sistema`, `Master`/`Host`, `Posti totali: <max_seats>` (omitted for unlimited and `0/0` events; `seats` is therefore in `EVENTBRITE_CONTENT_FIELDS`), `Dettagli`, the description, the association address and the `Evento su Telegram` link.

**Collections:** with `EVENTBRITE_COLLECTION_ROLEPLAY` / `EVENTBRITE_COLLECTION_BOARDGAMES` set, `_publish_blocking` adds the event to the collection of its type (`core.eventbrite.collections`: `POST /collections/{id}/events/`, `event_ids` as a string; undocumented by Eventbrite but confirmed on a real account), and `sync_eventbrite` moves it when `is_roleplay` is edited. A failure is only a warning to the admins. Already published events are not backfilled.

**Admin notices:** every Eventbrite notice about one event is sent as a reply to that event's admin card (`notify_admin(..., event_id=)`; plain message if the card is gone). The nightly cleanup summary covers several events, so it is a plain message.

**Approved card, second row** (when linked): `[🎟️ Eventbrite]` (dashboard) plus the Eventbrite-only action for the state: `[🚫 Annulla su Eventbrite]` (`eb_cancel_ask_<id>` → confirm `eb_cancel_do_<id>` / back `cancel_abort_<id>`) when `live`/`unpublished`, `[🔁 Completa annullamento]` (`eb_cancel_retry_<id>`) when `closed`, `[🎟️ Ricrea su Eventbrite]` (`eb_recreate_<id>`) when `canceled`. `sync_eventbrite` skips `closed` events so a cancellation in progress is never reopened or renamed back.

**Cancel / reactivate matrix** (Telegram `[❌ Annulla Evento]` after the admin confirmed, see §2.6 / `[♻️ Riattiva Evento]`; `eventbrite_status` is our view: `draft|live|unpublished|closed|canceled`):

| Telegram action | Eventbrite state | What happens | New `eventbrite_status` |
|---|---|---|---|
| Cancel | no orders | `unpublish` (reversible); if refused, falls through to the row below | `unpublished` |
| Cancel | has orders | quantity set to the number sold, event renamed `[ANNULLATO] …`, cancel API tried (Eventbrite refuses it while orders exist); admins get **one `❌ Name (n)` button per order** opening its *Cancel order* page (`order_cancel_url`, capped at 40), plus `[🎟️ Apri dashboard Eventbrite]` and `[🔁 Ho annullato tutto, completa]` (`eb_cancel_retry_<id>`; once the event is cancelled this temporary message is deleted, unlike the admin card) | `canceled` if accepted, else `closed` |
| `closed`, every order cancelled from the dashboard | `finish_eventbrite_cancellation` calls the cancel API: automatically from the poller (which sees no active orders left), or at once from `[🔁 …]`, which re-sends the links of the orders still active; the admins get `✅ Tutte le prenotazioni annullate…` | `canceled` |
| `[🚫 Annulla su Eventbrite]` (Eventbrite only, after `[✅ Sì, annulla su EB]`) | `live` / `unpublished` | same as *Cancel* with orders, but never unpublishes: without orders the event is cancelled for good. **The Telegram event stays approved** and nothing is posted to the discussion group; the booking reply just loses its Eventbrite link, released seats become free on Telegram, and the poller announces nothing (announcements require `eventbrite_status == 'live'`) | `canceled`, or `closed` until the orders are cancelled |
| Reactivate | `unpublished` | publish again, push content and capacity | `live` |
| Reactivate | `closed` | restore the name and force a capacity push | `live` |
| Reactivate | `canceled` | cannot be revived: admins get `[🎟️ Ricrea su Eventbrite]` (`eb_recreate_<id>`), which clears the Eventbrite info and publishes a new event | — |

The Eventbrite API has **no call to cancel an order or attendee**, and the refund call (`POST /orders/{id}/refunds/`) fails on free orders (confirmed on a real account), so orders are cancelled by an admin from the dashboard: each order's page has a *Cancel order* action, and Eventbrite emails the attendee. The dashboard runs on the logged-in browser session, not the API token, so the bot only sends the links. Confirmed URL formats: event dashboard `https://www.eventbrite.com/events/{eid}/dashboard/?eid={eid}`, order page `https://www.eventbrite.com/organizations/orders/{oid}`, cancel page `https://www.eventbrite.com/order-cancel?eid={eid}&oid={oid}&aid=` (`core.eventbrite.payload.dashboard_url` / `order_url` / `order_cancel_url`). Reactivating a `closed` event does not restore orders already cancelled.

**Nightly cleanup** (`bot.service.eventbrite_cleanup.delete_cancelled_eventbrite_events`, registered by `main.post_init` through `core.scheduler.runner.add_cron_job` at **23:59**, only when Eventbrite is enabled and `EVENTBRITE_DELETE_CANCELLED` is on). It deletes, **on Eventbrite only**, the Eventbrite events that are cancelled, so they are gone from the organizer account after midnight. **Telegram is not touched at all**: events, reservations, images, channel posts and discussion messages stay as they are, and nothing is posted to the discussion group. Candidates (`core.db.get_eventbrite_cleanup_candidates`) are linked events dated today or earlier (so a night with the bot offline is made up for the next one; finding them is one local SQL query, no API call) whose `eventbrite_status` is:

| `eventbrite_status` | Action |
|---|---|
| `canceled`, `unpublished` | `DELETE /events/{id}/` (`core.eventbrite.delete_eventbrite_event`; like cancel it works only while the event has no orders), then `clear_eventbrite_info` so the poller stops polling it, and the admin card is refreshed: an approved event shows `[🎟️ Pubblica su Eventbrite]` again, a cancelled one is unchanged. A `404`/`NOT_FOUND` (already deleted by hand) counts as deleted |
| `closed` (orders still being cancelled) | kept and listed in the admin summary |
| refused by Eventbrite (e.g. `CANNOT_DELETE`) | kept and listed in the admin summary |

Future-dated events are left alone until their day (so `[🎟️ Ricrea su Eventbrite]` stays usable), a `HIT_RATE_LIMIT` stops the run until the next night, and one failing event never blocks the others. The admins get a single plain-text summary (`🧹 Eliminati da Eventbrite N eventi annullati: …` / `⚠️ Non eliminati da Eventbrite: …`), only if something happened. The `Eliminati` line is sent only when `EVENTBRITE_CLEANUP_NOTIFICATIONS` is on (default off); the `Non eliminati` list is always sent, since an admin has to act on it. Not yet verified on a real account: whether Eventbrite lets you delete an event whose orders were all cancelled; if it refuses, the event is kept and reported.

**Admin panel.** In `[👥 Gestisci Iscritti]` Eventbrite rows are prefixed `🎟️` and are a single URL button to that order's page on Eventbrite (no ± buttons); the DB layer also refuses admin ± on them, and Telegram lookups (`book_seat`, `unbook_seat`, `admin_add_subscriber`, `admin_remove_subscriber`, `get_reservation_by_user`) never match Eventbrite rows, so a Telegram user named "Mario R." cannot touch an Eventbrite booking. Attendees are stored as first name plus initial (`attendee_display_name`); emails are never stored.

**Eventbrite API notes.** Eventbrite has no sandbox (test with `EVENTBRITE_LISTED=false`) and is eventually consistent, so POST response bodies are trusted instead of reading back. The description uses structured content (the legacy `description` field is deprecated); its HTML is limited to `p, b, em, ul, li, a`, so multi-line text becomes one `<p>` per line.

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
│   │   ├── control.py    # /bot_pause, /bot_resume, /bot_status, /bot_eventbrite_only_toggle, /bot_eventbrite_venue
│   │   ├── public.py     # /start, /event_next, /event_subs
│   │   ├── ingestion.py  # Channel interception (process_message) and /event_process (/ep)
│   │   ├── albums.py     # Media-group (album) buffering for channel posts and admin uploads
│   │   ├── extraction.py # handle_event_extraction: AI parse -> pending event -> admin approval card
│   │   ├── edit.py       # /event_edit_* (EDIT_COMMAND_FIELDS / FIELD_EDITORS)
│   │   ├── subscribers.py # /event_sub_add, /event_sub_remove, ForceReply add-subscriber prompt
│   │   ├── recap.py      # /recap_generate and discussion-group forward handling
│   │   ├── repost.py     # /event_repost, /event_schedule_invoke
│   │   ├── repost_schedule.py # /event_schedule, /event_schedule_update, /event_schedule_list
│   │   ├── story.py      # /event_regenerate_story
│   │   └── eventbrite.py # /event_publish_eventbrite
│   ├── callbacks/        # Inline button (CallbackQuery) handlers
│   │   ├── router.py     # handle_callback_query + CALLBACK_ROUTES prefix table
│   │   ├── events.py     # Publish / discard / cancel / reactivate event cards, Eventbrite publish/recreate buttons
│   │   ├── notices.py    # Cancellation / reactivation notices to the discussion group
│   │   ├── recap.py      # Publish / discard recap, article draft (Astro / WordPress) & publish
│   │   ├── booking.py    # ➕ Prenota / 🚫 Esauriti / ➖ Annulla
│   │   ├── subscribers.py # 👥 Gestisci Iscritti panel (± seats, add prompt, close)
│   │   ├── schedule.py   # Repost schedule weekday toggles, delete, close
│   │   └── venues.py     # /bot_eventbrite_venue picker (ebvenue_<id>) and its [❌ Chiudi] (ebvenue_close)
│   ├── service/          # Telegram side effects shared by handlers and callbacks
│   │   ├── posts.py      # update_event_messages: sync channel post + discussion reply (with RetryAfter retry)
│   │   ├── booking.py    # Seat booking/unbooking flows and same-day conflict warnings
│   │   ├── notices.py    # send_admin_action_notice, send_discussion_notice
│   │   ├── mentions.py   # User/subscriber mention formatting
│   │   ├── eventbrite/   # Eventbrite flows; import public names from bot.service.eventbrite
│   │   │   ├── common.py  # admin notices/card refresh, venue names, collections, unlinking deleted events
│   │   │   ├── publish.py # publish (background task), recreate
│   │   │   ├── sync.py    # capacity/content/logo sync, seat claim on booking, logo retry
│   │   │   └── cancel.py  # cancel, finish cancellation, Eventbrite-only cancel, reactivate
│   │   ├── eventbrite_poll.py # Scheduler job: poll Eventbrite orders into the shared seat pool
│   │   └── eventbrite_cleanup.py # 23:59 job: delete cancelled events from Eventbrite (Telegram untouched)
│   └── event_generator/  # /event_generate
│       ├── command.py    # Telegram command handler
│       ├── pipeline.py   # Generation pipeline, caption limit, admin preview
│       ├── ai.py         # Gemini prompt + response normalization
│       └── bgg.py        # BoardGameGeek search and cover download
├── core/
│   ├── __init__.py
│   ├── config.py         # Loads environment variables (.env), paths, constants
│   ├── ai_parser.py      # Gemini: generate_text, event extraction (+ seat safety net), article writing (HTML for WP, Markdown for Astro)
│   ├── log_utils.py      # Daily rotating log handler, monthly log zip archiving, JobLinesToDebug filter (poller job lines)
│   ├── instagram.py      # Meta Graph API: container creation & story publishing
│   ├── db/               # SQLite data access (public API: `from core.db import ...`)
│   │   ├── connection.py # get_connection, transaction(), fetch_one/fetch_all/execute, @db_safe
│   │   ├── schema.py     # CREATE TABLEs + COLUMN_MIGRATIONS / VERSIONED_MIGRATIONS applied by init_db()
│   │   ├── events.py     # events table: insert/update/delete, lookups, recap & upcoming queries
│   │   ├── reservations.py # reservation lookups, identity normalization, same-day conflicts
│   │   ├── seats.py      # Booking rules: book/unbook, admin seat ± and subscriber add/remove
│   │   └── scheduled.py  # scheduled_events (repost templates)
│   ├── scheduler/        # APScheduler jobs
│   │   ├── runner.py     # start_scheduler / stop_scheduler (job timetable)
│   │   ├── recap.py      # 16:00 daily recap card for admin approval
│   │   ├── archive.py    # 23:59 image archiving + booking shutdown, 00:05 monthly log zips
│   │   └── reposts.py    # 09:00 digest of scheduled reposts due today
│   ├── eventbrite/       # Eventbrite REST API (public API: `from core.eventbrite import ...`)
│   │   ├── client.py     # eventbrite_enabled, eb_get / eb_post, EventbriteError, paginate
│   │   ├── payload.py    # Pure builders: start/end, event payload, description modules, ticket_quantity, names, dashboard URLs
│   │   ├── collections.py # Eventbrite collections: add/remove an event (by event type)
│   │   ├── venues.py     # get_venue, eventbrite_venue_ids (default + alternatives)
│   │   ├── events.py     # create/update/get event, publish/unpublish/cancel, structured-content description
│   │   ├── tickets.py    # Free ticket class create / quantity update / close sales when full
│   │   ├── media.py      # Three-step logo upload (2:1 padding, browser User-Agent, retries)
│   │   └── orders.py     # fetch_active_orders (names and seat counts only)
│   ├── astro/            # Astro site publishing (public API: `from core.astro import ...`)
│   │   ├── client.py     # GitHub API request helper, lazy boto3 R2 client
│   │   ├── storage.py    # upload_media to R2 (resize, keys, public URL)
│   │   ├── github.py     # branches, file commits, merge, delete
│   │   └── content.py    # slug, front matter, publish_article (draft branch), update_article_status (merge)
│   └── wordpress/        # WordPress REST API (public API: `from core.wordpress import ...`)
│       ├── client.py     # Credentials, auth headers, wp_get / wp_post (with timeouts)
│       ├── categories.py # WP_POST_CATEGORY / slug / name -> category IDs
│       └── content.py    # upload_media, publish_article (draft), update_article_status
├── utils/
│   ├── __init__.py
│   ├── date_utils.py     # Date parsing, format validation (DD-MM-YYYY [HH:MM]), and anomaly checks
│   ├── image_utils.py    # Pillow image manipulation: collages, story generation, date folder resolution
│   └── templates/        # Every user-facing text, one module per area
│       ├── common.py, event.py, recap.py, subscribers.py, reposts.py, control.py, eventbrite.py
│       └── booking.py, edit.py, approval.py, public.py, wordpress.py, generator.py, keyboards.py, commands.py
├── scripts/              # Utility and maintenance scripts
│   ├── generate_story.py # Utility script to manually generate Instagram Stories by event ID
│   ├── fix_event_keyboards.py # Utility script to synchronize event inline buttons with SQLite IDs
│   ├── clean_db.py       # Utility script to wipe database tables and clean image folders
│   ├── unzip_images.py   # Utility script to extract archived images by directory or date range
│   ├── eventbrite_setup.py # Eventbrite helper: check token, list orgs/venues, create/update venues, create collections
│   ├── eventbrite_inspect.py # Read-only Eventbrite check: quantity_sold vs orders/attendees (--watch)
│   └── test_ig.py        # Diagnostic script to test Meta Graph API tokens
├── tests/                # unittest/pytest suite mirroring the source tree; shared helpers in tests/support/ (see §3.3)
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
  - `messages.py`: `resolve_message`, `command_argument` / `command_tokens`, `truncate_caption` / `CAPTION_LIMIT` (defined once in `utils/templates/common.py`), `edit_card(query, text, **kw)` (edits a callback card in place: the caption of a photo card, cut to `CAPTION_LIMIT`, else the text), `with_html_fallback(call)` (send with `parse_mode="HTML"`, retry as plain text), `send_with_reply_fallback` (reply in the discussion group, fall back to a plain send if the reply target is gone), `reply_in_chunks`, `send_image_or_error`, `private_chat_link`, `is_not_modified_error`.
  - `media.py`: `download_media_bytes`, `download_first_image` (largest photo, then image document), `read_image_file`.
  - `parsing.py`: `parse_seats_input(value)`, the single seat parser for `/event_edit_seats` and the `SEATS` argument of `/event_repost` / `/event_schedule_invoke`. It returns `None` for unlimited (`null`, `nessuno`, `illimitati`, `unlimited`, `none`, `0`, empty), `(free, total)` for `X/Y`, or `(None, total)` for a bare integer. Unlimited events display `UNLIMITED_SEATS_DISPLAY = "no limit"`, the same string the AI parser outputs. Also here: `contains_event_keywords` / `EVENT_KEYWORD_PATTERNS` (the pre-AI keyword filter) and `extract_event_id_from_reply`; `resolve_event_id(message)` combines it with a numeric command argument (`/cmd <id>`).
  - `previews.py`: `send_admin_preview` (approval card as photo caption or text), `build_admin_warning_block` / `date_anomaly_warning`, and `notify_quota_depleted`, the Gemini credit alert used by extraction, recap WordPress generation and `/event_generate`.
- **`bot/state.py`:** `runtime_state` (`BotRuntimeState`) holds the pause flag (`is_paused`) and the last published recap (`last_recap_message_id`, `last_recap_events`). `bot/callbacks/recap.py` records a published recap via `remember_published_recap(message_id, events)`; `bot/handlers/recap.py` reads it when the recap is auto-forwarded into the discussion group.
- **`bot/handlers/`:**
  - `albums.py` owns `media_groups` / `admin_media_groups`, module-level dicts (changed in place, never reassigned) that buffer album photos for channel ingestion and for admin `/ep` / `/event_edit_image`.
  - `extraction.handle_event_extraction` is the single ingestion pipeline. Channel posts, albums, `/ep`, `/event_repost` and `/event_schedule_invoke` all go through it.
  - **`/event_edit_*` dispatch (`edit.py`):** `EDIT_COMMAND_FIELDS` maps each command to a DB field: `/event_edit_title`, `/event_edit_date`, `/event_edit_system`, `/event_edit_seats`, `/event_edit_booked`, `/event_edit_host`, `/event_edit_extra`, `/event_edit_extra_add`, `/event_edit_description`, `/event_edit_image` and `/event_edit_type`. `FIELD_EDITORS` maps fields/commands that need custom logic (`image_path`, `date`, `seats`, `booked_seats`, `extra_info`, `/event_edit_extra_add`, `is_roleplay`) to editor coroutines `(update, event_id, current_event, value) -> bool`; other fields are written verbatim. Editors raise `EditInputError(reply, parse_mode)` for invalid input. To add an editable field, add one entry to `EDIT_COMMAND_FIELDS` (plus a `FIELD_EDITORS` entry if it needs parsing) and register the command in `main.py`.
  - Shared flows: `subscribers._add_subscriber_and_notify` (used by the ForceReply prompt and `/event_sub_add`), `subscribers._parse_subscriber_command` (shared by `/event_sub_add` and `/event_sub_remove`), `public._reply_with_participants` (used by `/event_subs` and the `start=subs_<id>` deep link), and `repost.extract_repost_content` (shared by repost and repost scheduling).
- **`bot/callbacks/`:** `router.handle_callback_query` is the only `CallbackQueryHandler` registered in `main.py`. It walks `CALLBACK_ROUTES`, an ordered `(prefix, handler)` table, and calls `handler(query, context, payload)` with the callback data that follows the prefix. To add a button, give it a new callback prefix (one that is not a prefix of an existing entry; a test enforces this), write the handler in the matching feature module, and add one row to `CALLBACK_ROUTES`.
- **`bot/service/`:**
  - `posts.update_event_messages` re-renders an event's channel post (edit caption/text, switching kind only on Telegram's "no caption/text" error) and its discussion-group booking reply, retrying on `RetryAfter`.
  - `booking.py` handles seat booking/unbooking and same-day conflict warnings.
  - `notices.py` provides `send_admin_action_notice` and `send_discussion_notice`.
  - `mentions.format_subscriber_tag` is the single tag formatter for stored reservations (`@username`, `tg://user` link, or name).
  - `eventbrite/` holds the Eventbrite flows (see §2.11), split into `common`, `publish`, `sync` and `cancel`; `__init__.py` re-exports the public functions, so other modules import from `bot.service.eventbrite`. In tests, patch a name in the submodule that *calls* it (e.g. `bot.service.eventbrite.publish.publish_event_to_eventbrite`); a patch on the package does not reach calls made between submodules. `posts.update_event_messages` is the single hook point: after the Telegram sync it calls `sync_eventbrite`, and it edits the discussion reply as *text* (`format_discussion_booking_message`) so the Eventbrite link can appear. `publish.py` and `cancel.py` import `update_event_messages` inside their functions, because `posts.py` imports `sync_eventbrite` at module level (patch `bot.service.posts.update_event_messages` in tests). `eventbrite_poll.py` builds `SimpleNamespace(bot=bot)` as the context, since services only use `context.bot`.


### 3.2. `core/` Package Architecture
- **Configuration is read at call time** (`config.ADMIN_CHAT_ID`, `config.DB_PATH`, `config.WP_URL`, `config.IG_ACCESS_TOKEN`, …), never copied at import. Tests and scripts redirect the database by setting/patching `core.config.DB_PATH`.
- **`core.db` and `core.wordpress` are facades.** Their `__init__.py` re-exports the public API (`__all__`), so callers write `from core.db import get_event`. The submodules call each other directly, so patch a DB/WordPress function in the module that *uses* it. HTTP for WordPress goes through `core.wordpress.client` (patch `core.wordpress.client.requests.*`). `core.scheduler` is a set of job modules with an empty `__init__.py`, the same as the `bot/` packages: import `core.scheduler.runner.start_scheduler`, `core.scheduler.recap.generate_daily_recap`, etc.
- **`core.eventbrite` is a facade too** (same rules as `core.wordpress`): `__init__.py` re-exports the public API, HTTP goes through `core.eventbrite.client` (patch `core.eventbrite.client.requests.*`), calls are synchronous with a 30 s timeout and async callers wrap them in `asyncio.to_thread`. Branch on `EventbriteError.error` (the API's error constant), never on its description. `payload.py` is pure and heavily unit-tested.
- **DB plumbing (`core/db/connection.py`):**
  - `transaction()` yields a cursor with dict-like rows, commits or rolls back, and always closes the connection.
  - `fetch_one` / `fetch_all` / `execute` / `execute_many` wrap single statements.
  - `@db_safe(default)` logs `DB error in <function>: …` and returns `default` (`default=list` gives a fresh `[]`), so callers keep the old "never raises" contract.
  - `get_connection()` returns a raw connection for scripts.
  - SQL string literals use single quotes (`status IN ('approved', 'cancelled')`); double quotes are reserved for identifiers.
- **Schema changes:** add the column to the `CREATE TABLE` in `core/db/schema.py` *and* to `COLUMN_MIGRATIONS`, so existing databases get an `ALTER TABLE` on the next start. For a change that is not a new column (rename, data rewrite), add `{N: (sql, ...)}` to `VERSIONED_MIGRATIONS` and set `SCHEMA_VERSION = N`: `init_db()` runs it once on databases whose `PRAGMA user_version` is lower. `init_db()` also switches the database to WAL journal mode (`bot_database.db-wal` / `-shm` files appear next to it; copy all three, or stop the bot, before backing it up).
- **Eventbrite columns** are written only through `set_eventbrite_info` / `clear_eventbrite_info` (a whitelist); they are deliberately not in `EDITABLE_EVENT_FIELDS`, so `/event_edit_*` cannot set them. `init_db()` also applies an `INDEXES` tuple (a unique index on `reservations(event_id, eventbrite_order_id)`).
- **Seat bookkeeping (`core/db/seats.py`):** every reservation change runs in one transaction with `_load_seat_state` (event exists / not cancelled / capacity) and `_set_booked_seats`, which rewrites both `booked_seats` and the `free/max` `seats` string. `normalize_identity` applies the legacy rule "a username with spaces is a full name".
- **Dates:** pure date helpers live in `utils/date_utils.py` (`parse_date_tuple_from_str`, `event_date_tuple`, `are_events_on_same_day`); `core.db` only queries.
- **Gemini (`core/ai_parser.py`):** `generate_text(prompt)` is the single entry point to `config.GEMINI_MODEL` and raises `GeminiQuotaError` on quota/credit errors. `strip_json_fence` and `coerce_bool` are shared with `bot/event_generator/ai.py`.
- **Texts:** all user-facing Telegram texts (replies, popups, notices, inline button labels, `BotCommand` descriptions) live in the `utils/templates/` package (one module per area, imported by name, e.g. `from utils.templates.common import POPUP_CLOSED`) as constants or `format_*` helpers; handlers, callbacks and services import them instead of using inline literals. Logging, exceptions, `callback_data` and the LLM prompt stay where they are.
- **Scheduler:** `runner.add_interval_job(func, minutes, args)` registers a repeating, non-overlapping job on the running scheduler (the Eventbrite poller) and `runner.add_cron_job(func, hour, minute, args)` a daily one (the Eventbrite cleanup at 23:59); `core/` never imports `bot/` for them.
- **External HTTP:** WordPress calls default to a 30 s timeout (category lookups 10 s). Instagram Graph calls run in a worker thread (`asyncio.to_thread`) with a 30 s timeout, so a slow Meta API cannot freeze the bot.
- **Known layering debt:** `core/scheduler/recap.py` still imports `bot.keyboards.get_recap_approval_keyboard` (core → bot). Moving the recap job into `bot/` would remove it.

### 3.3. `tests/` Layout
- **Mirrors the source tree.** There is one test file per module under test: `tests/bot/handlers/test_edit.py` tests `bot/handlers/edit.py`, `tests/core/scheduler/test_archive.py` tests `core/scheduler/archive.py`, and `tests/test_main.py` tests `main.py`. Add new tests next to the module they exercise, not in per-feature or per-ticket files. `tests/` and each subfolder are packages, so no `sys.path` setup or `conftest.py` is needed. Both `python3 -m pytest tests` and `python3 -m unittest discover -s tests -t .` work.
- **`tests/support/` helpers:**
  - `db.py`: `TempDBMixin` (a fresh SQLite file per test by patching `core.config.DB_PATH`, plus `self.temp_dir`, `init_db()` already run), `sample_event` / `create_event(status=..., **fields)`, and shared fixtures such as `create_subscribed_event()`.
  - `telegram.py`: `make_update`, `admin_update`, `make_message` (media fields explicitly `None`), `channel_message`, `admin_card(event_id)`, `callback_update(data) -> (update, query)`, `make_context`, `make_bot`, `make_user`, `telegram_photo(bytes)`.
  - `config.py`: `patched_config(**settings)`, `as_admin_chat()`, `wordpress_credentials()`, `eventbrite_credentials(**overrides)` (Eventbrite fully configured).
  - `images.py`: `make_image`, `image_bytes`, `image_file`.

  Prefer these over hand-built `MagicMock`s.
- **Patching convention:**
  - Settings: patch `core.config.*` (`patched_config(...)`).
  - Functions: patch them where they are *used*, e.g. `bot.handlers.extraction.parse_event_message` or `core.wordpress.client.requests.post`.
  - Isolation: tests must not read real tokens or touch the real `DB_PATH` / `DATA_DIR`. Point `DATA_DIR` at `self.temp_dir` for jobs that move or zip images.

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
| `wp_post_url` | TEXT | | Associated article draft link (WordPress edit URL or GitHub file URL) |
| `article_backend` | TEXT | | `astro` when the article was drafted by the Astro backend |
| `article_ref` | TEXT | | Astro draft reference (the `serata/<slug>` branch) |
| `is_roleplay` | INTEGER | DEFAULT 0 | 1 if roleplaying event (Master), 0 if non-RPG (Host) |
| `discussion_message_id` | INTEGER | | Message ID of the booking reply in the discussion group |
| `discussion_chat_id` | TEXT | | Chat holding that reply |
| `admin_message_id` | INTEGER | | Message ID of the event card in the admin chat |
| `eventbrite_event_id` | TEXT | | Eventbrite event ID (NULL = not on Eventbrite) |
| `eventbrite_url` | TEXT | | Public Eventbrite event URL |
| `eventbrite_ticket_class_id` | TEXT | | ID of the single free ticket class |
| `eventbrite_status` | TEXT | | Our view of the Eventbrite state: `draft`, `live`, `unpublished`, `closed` (cancelled in Telegram, has orders, Eventbrite not cancelled yet) or `canceled` |
| `eventbrite_quantity_total` | INTEGER | | Last ticket quantity pushed (skips no-op calls) |
| `eventbrite_content_version` | INTEGER | DEFAULT 0 | Structured-content page version (each write sends last + 1) |
| `eventbrite_synced_at` | TEXT | | Timestamp of the last successful poll |

### Table: `reservations`
| Column | Type | Constraints / Default | Description |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Unique reservation ID |
| `event_id` | INTEGER | | Foreign key referencing `events(id)` |
| `user_id` | INTEGER | | Telegram User ID of participant |
| `username` | TEXT | | Telegram username (without @) or null if user has no handle |
| `full_name` | TEXT | | Display / full name for users without a username |
| `seats_booked` | INTEGER | DEFAULT 0 | Number of seats booked by this user |
| `source` | TEXT | DEFAULT 'telegram' | `telegram` or `eventbrite` |
| `eventbrite_order_id` | TEXT | | Eventbrite order ID (Eventbrite rows only; `user_id`/`username` are NULL, `full_name` is `Mario R.`). Unique per `(event_id, eventbrite_order_id)` |

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
| `advance_days` | INTEGER | DEFAULT 0 | Days before the event the digest reminder is sent (0-30; 0 = same day) |

---

## 5. Environment Variables (`.env`)

| Variable | Description | Example / Format |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Token provided by `@BotFather`. Required: without it (or `ADMIN_CHAT_ID`) `main.py` logs the missing names (`core.config.missing_required_settings`) and exits | `123456789:ABCdef...` |
| `PUBLIC_CHANNEL_ID` | Telegram Channel ID | `-1001234567890` |
| `ADMIN_CHAT_ID` | Admin User ID or Admin Group ID | `123456789` or `-100...` |
| `GEMINI_API_KEY` | Google AI Studio API Key | `AIzaSy...` |
| `GEMINI_MODEL` | Gemini model name | `gemini-3.1-flash-lite` |
| `BGG_API_TOKEN` | (Optional) BoardGameGeek API token for the `/event_generate` box covers; without it (or on a 401 / no result) covers come from BGG by ID (from Wikidata or Gemini's checked guess), then Wikipedia, then a Gemini-verified Bing image search | `xxxxxxxx` |
| `ARTICLE_BACKEND` | (Optional) `astro` (default) or `wordpress`; an invalid value logs a warning and falls back to `astro` | `astro` |
| `ASTRO_GITHUB_REPO` | (Optional) Website repo | `GildaDelGrifone/GdG-Website` |
| `ASTRO_GITHUB_BRANCH` | (Optional) Branch the site deploys from | `main` |
| `ASTRO_GITHUB_TOKEN` | Fine-grained token, Contents read/write on the website repo only | `github_pat_xxxx` |
| `ASTRO_CONTENT_DIR` | (Optional) Content folder of the articles in the repo | `src/content/serate` |
| `ASTRO_BASE_URL` | (Optional) Public site URL used for the published link | `https://www.gildadelgrifonetorino.it` |
| `R2_ACCOUNT_ID` | Cloudflare account id | `abc123` |
| `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | R2 API token credentials (Object Read & Write) | `xxxx` |
| `R2_BUCKET` | (Optional) R2 bucket | `gdg-media` |
| `R2_PUBLIC_URL` | Public base URL of the bucket, no trailing slash | `https://pub-xxxx.r2.dev` |
| `WP_URL` | WordPress base URL (only with `ARTICLE_BACKEND=wordpress`) | `https://www.gildadelgrifonetorino.it` |
| `WP_USERNAME` | WordPress username | `direttivogilda` |
| `WP_APP_PASSWORD` | WordPress Application Password | `xxxx xxxx xxxx xxxx` |
| `WP_POST_CATEGORY` | (Optional) Category ID or name for generated posts | `12` or `Eventi` |
| `IG_ACCESS_TOKEN` | Meta Long-Lived Graph API User Access Token | `EAA...` |
| `IG_ACCOUNT_ID` | Instagram Business Account Numeric ID | `178414...` |
| `DATA_DIR` | (Optional) Custom path for storage | `/var/gdg_data` |
| `LOG_LEVEL` | (Optional) Logging level: `DEBUG`, `INFO` (default), `WARNING`, `ERROR`, `CRITICAL`; a typo falls back to `INFO`. `DEBUG` also shows the per-minute Eventbrite poller job lines (`JobLinesToDebug` in `core/log_utils.py`); httpx stays at `WARNING` regardless. Needs a restart | `INFO` |
| `REPOSTS_TIME`, `RECAP_TIME`, `ARCHIVE_IMAGES_TIME`, `ARCHIVE_LOGS_TIME`, `EVENTBRITE_CLEANUP_TIME` | (Optional) Daily job times as 24h `HH:MM` local time, parsed by `core.config._env_time` (a typo falls back to the default). The 09:00 / 16:00 / 23:59 / 00:05 times quoted elsewhere in this file are the defaults. Needs a restart | `09:00`, `16:00`, `23:59`, `00:05`, `23:59` |
| `RECAP_WEEKDAYS` | (Optional) Weekdays with an automatic recap, comma-separated, `0` = Monday (`core.config._env_weekdays`; a typo falls back to the default). Needs a restart | `0,2,4,5,6` |
| `EVENT_START_TIME` | (Optional) Game night start time (`HH:MM`) shown in the recap texts ("Ci vediamo alle ...") and the recap story footer; also the default of `EVENTBRITE_DEFAULT_START_TIME` and of `utils.date_utils.extract_event_datetime` | `20:45` |
| `RECAP_CONTACTS` | (Optional) Comma-separated Telegram handles to contact to propose an event, used in the recap texts and the article prompt | `@Destard,@ManueleAbi` |
| `MAX_EVENTS_PER_ROW` | (Optional) Maximum number of event images per row in collages. Numeric settings (this and the `EVENTBRITE_*` numbers) fall back to their default on a typo (`_env_int` / `_env_float`) | `4` |
| `ALLOW_GROUP_EVENT_NEXT` | (Optional) Enable/disable `/event_next` in discussion group (`true`/`false`) | `true` |
| `EVENTBRITE_TOKEN` | (Optional) Eventbrite private OAuth token | `ABC...` |
| `EVENTBRITE_ORGANIZATION_ID` | (Optional) Eventbrite organization ID (`scripts/eventbrite_setup.py --orgs`) | `1234567890` |
| `EVENTBRITE_VENUE_ID` | (Optional) Venue ID, created once with `scripts/eventbrite_setup.py --create-venue`. The integration is enabled only when token, organization and venue are all set | `1234567` |
| `EVENTBRITE_ORGANIZER_ID` | (Optional) Sent as `organizer_id` when set | `1234567` |
| `EVENTBRITE_TIMEZONE` | (Optional) Time zone of event dates | `Europe/Rome` |
| `EVENTBRITE_CURRENCY` | (Optional) Currency of the (free) tickets | `EUR` |
| `EVENTBRITE_LISTED` | (Optional) `false` = unlisted events (useful for testing) | `true` |
| `EVENTBRITE_DEFAULT_START_TIME` | (Optional) Start time when the event date has no time (default: `EVENT_START_TIME`) | `20:45` |
| `EVENTBRITE_EVENT_DURATION_HOURS` | (Optional) Event length used for the end time | `4` |
| `EVENTBRITE_UNLIMITED_CAPACITY` | (Optional) Eventbrite capacity for events with unlimited seats (Telegram stays unlimited) | `50` |
| `EVENTBRITE_POLL_MINUTES` | (Optional) Poll interval for Eventbrite bookings | `2` |
| `EVENTBRITE_DELETE_CANCELLED` | (Optional) At 23:59 delete cancelled events dated today or earlier from Eventbrite (`true`/`false`); Telegram is never touched | `true` |
| `EVENTBRITE_CLEANUP_NOTIFICATIONS` | (Optional) Send the nightly `🧹 Eliminati da Eventbrite N eventi annullati` message to the admin chat (`true`/`false`). Events the cleanup could not delete are reported either way | `false` |
| `EVENTBRITE_FULL_SYNC_MINUTES` | (Optional) How often the poller fetches the full order list even when `quantity_sold` is unchanged (safety net); `0` = on every poll | `30` |
| `EVENTBRITE_VENUE_ID_ALTERNATIVES` | (Optional) Extra venue ids, comma-separated. `EVENTBRITE_VENUE_ID` stays the default; with several, `/bot_eventbrite_venue` picks the one used for new events (in memory) | `2345678,3456789` |
| `EVENTBRITE_ONLY_MODE` | (Optional) Initial state of the Eventbrite-only mode (`true`/`false`); `/bot_eventbrite_only_toggle` changes it at runtime (in memory) | `false` |
| `EVENTBRITE_COLLECTION_ROLEPLAY` / `EVENTBRITE_COLLECTION_BOARDGAMES` | (Optional) Eventbrite Collection ids: published events join the roleplay one when `is_roleplay`, the board games one otherwise; both empty = off. Create one with `scripts/eventbrite_setup.py --create-collection "NAME"` (the API creates it as a draft; publish it from the dashboard) | none |
| `EVENTBRITE_BOOKING_NOTIFICATIONS` | (Optional) Announce Eventbrite bookings/releases in the discussion group, or in the admin chat for Eventbrite-only events (`true`/`false`); seats sync either way | `true` |

---

## 6. Templates & Character Limit Handling
Every user-facing Telegram text lives in the `utils/templates/` package, one module per area. Callers import from the specific module (`from utils.templates.common import POPUP_CLOSED`); `__init__.py` re-exports nothing. Wording is changed there, never at the call site. Logging, exceptions, `callback_data`, URLs and the LLM prompt are not templates and stay in the code. Texts are either constants or `format_*` helpers; helpers take raw values and `html.escape` them themselves when the message goes out with `parse_mode="HTML"`.

| Module | What it holds |
|---|---|
| `common.py` | `format_event_title_link` (escaped, bold, linked to the channel post), `ASSOCIATION_ADDRESS`, `CAPTION_LIMIT` (Telegram caption length, 1024), `EVENTBRITE_ROW_PREFIX`, generic replies and popups (`UNAUTHORIZED_REPLY`, `POPUP_EVENT_NOT_FOUND`, `POPUP_CLOSED`, `NO_TEXT_IN_REPLIED_MESSAGE`), `format_seats_count`, `format_admin_failure/success` |
| `event.py` | `format_public_event_message` (channel post), `format_instagram_story`, `format_event_seats`, `format_discussion_booking_message` (`👇 Gestisci qui la tua prenotazione!`, plus the Eventbrite link when the event is `live`) |
| `recap.py` | `format_contacts` (Italian list of `RECAP_CONTACTS`), `recap_generate_text` (full recap; footer uses `RECAP_CONTACTS` and `EVENT_START_TIME`; switches to the slim variant when it exceeds the 1024-character caption limit), `recap_links_text` (discussion comment with linked titles), `/recap_generate` and recap-job messages |
| `subscribers.py` | `format_reservation_subscriber_display`, `format_event_participants_message`, the subscribers management panel (`format_subscribers_panel`), `/event_sub_add` / `/event_sub_remove` usage and the add-subscriber prompt (`ADD_SUBSCRIBER_PROMPT_MARKER` is matched by `handle_admin_reply`) |
| `reposts.py` | `format_schedule_repost_message`, `REPOST_UPDATE_REMINDER`, `/event_repost` and `/event_schedule*` replies, the daily digest and list entries, schedule popups |
| `control.py` | `/bot_pause`, `/bot_resume`, `/bot_status`, Eventbrite-only mode and the venue picker texts |
| `eventbrite.py` | admin messages for publish/cancel/reactivate/logo/sync, poller notices (bookings, releases, overbooking), nightly-cleanup summary, `/event_publish_eventbrite` replies |
| `booking.py` | booking/unbooking notices, same-day conflict warning, admin seat-action notice, cancellation/reactivation status notice |
| `edit.py` | `/event_edit_*` replies and errors |
| `approval.py` | status suffixes of the admin card (`APPROVED_SUFFIX`, …; the suffix swap in `bot/callbacks/events.py` strips them by exact match), preview warnings, approval/cancellation popups, story captions |
| `public.py` | `/event_process`, `/event_next`, `/event_subs` and `/start` texts |
| `wordpress.py` | recap approval card suffixes and article (WordPress / Astro) messages |
| `generator.py` | `/event_generate` usage, progress and results |
| `keyboards.py` | every inline button label (`BUTTON_*`) and the label formatters used by `bot/keyboards.py` |
| `commands.py` | `DEFAULT_COMMAND_DESCRIPTIONS` / `ADMIN_COMMAND_DESCRIPTIONS`, the (command, description) pairs `main.post_init` registers |

`tests/utils/test_templates.py` checks the formatters and that every text constant of every module is a non-empty string.

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
5. Call `core.instagram.publish_instagram_story()` (after a media upload for a public image URL: R2 with `ARTICLE_BACKEND=astro`, WordPress otherwise) from `_send_story_preview` in `bot/callbacks/events.py` and from `_run_post_recap_pipeline` in `bot/callbacks/recap.py`.
