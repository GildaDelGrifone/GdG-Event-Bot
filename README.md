# GdG-Event-Bot

Automated social media and event management bot for **Gilda del Grifone**, a tabletop gaming association based in Turin, Italy.

This application monitors a Telegram channel, extracts event information using **Google Gemini AI**, generates standardized social media graphics (Instagram Stories, Collages), handles live seat bookings via interactive buttons, and publishes recap articles to **WordPress**.

---

## Table of Contents
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration (`.env`)](#configuration-env)
- [Running the Application](#running-the-application)
- [Telegram Commands & Workflow](#telegram-commands--workflow)
  - [1. New Event Flow](#1-new-event-flow)
  - [2. Live Seat Booking](#2-live-seat-booking)
  - [3. Daily Recap Flow](#3-daily-recap-flow)
  - [4. Admin Event Editing (Reply Commands)](#4-admin-event-editing-reply-commands)
  - [5. Bot Control Commands](#5-bot-control-commands)
- [Storage & Folder Structure](#storage--folder-structure)
- [Maintenance & Diagnostic Scripts](#maintenance--diagnostic-scripts)
- [Development & Tests](#development--tests)

---

## Features

- **Automated Telegram Channel Interception:** Listens to the public announcement channel. When an admin posts a message, the bot parses the content with Gemini AI. If confirmed as a bookable event, the bot deletes the raw post and routes it to an admin review chat; non-event announcements, reminders, and notices are left untouched in the channel.
- **Interactive Live Booking System & Same-Day Conflict Warnings:** Published events feature inline `[➕ Prenota]`, `[👥 Lista]`, and `[➖ Annulla]` buttons across both the announcement channel and discussion group. Users can reserve or release seats directly in Telegram; message text updates live to reflect remaining availability, and reply notifications are posted automatically. The `[👥 Lista]` button deep-links to a private DM with the bot (`/start subs_{id}`), providing a full roster of participants without generating chat spam. If a user reserves a seat on multiple valid events on the same day, the bot automatically warns them in chat with links to all conflicting events so they can choose which to keep.
- **Event Cancellation:** Admins can cancel any event at any time using a persistent `[Cancel]` button. Cancelled events update live in the channel and are flagged as `[ANNULLATO]` with zero seats in recaps and graphics.
- **Daily Recaps & Multi-Image Collages:** Automatically runs at 16:00 on gaming days (Mon, Wed, Fri, Sat, Sun) or on-demand via `/recap_generate`. Stitches event artwork into clean collages (wrapped into multiple rows via `MAX_EVENTS_PER_ROW`) without cropping borders.
- **Instagram Story Generator:** Programmatically builds 1080x1920 Instagram Story cards for individual events and daily recaps using Pillow (handling top banner artwork, dynamic text wrapping, seat counters, and association location footers).
- **WordPress REST API Integration:** AI writes an Italian recap article embedding event details, Telegram message links, and individual event pictures (max 400x400). The recap collage is set as the featured image. Posts can be published publicly directly from Telegram.

---

## Requirements

- **Python 3.10+**
- **SQLite 3**
- Telegram Bot token (from `@BotFather`) with admin rights on your public channel
- Google Gemini API key (Google AI Studio)
- WordPress site with REST API and an Application Password enabled
- (Optional) Meta Developer Account with Instagram Graph API access

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Destard20/GdG-Event-Bot.git
   cd GdG-Event-Bot
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up configuration:**
   ```bash
   cp .env.example .env
   # Edit .env with your tokens and credentials
   ```

---

## Configuration (`.env`)

Create or edit the `.env` file in the root directory:

```env
# Telegram Configuration
TELEGRAM_BOT_TOKEN=your_bot_token_here
PUBLIC_CHANNEL_ID=-100xxxxxxxxxx
ADMIN_CHAT_ID=your_admin_user_or_group_id

# Google Gemini AI Configuration
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.1-flash-lite

# WordPress REST API Configuration
WP_URL=https://www.gildadelgrifonetorino.it
WP_USERNAME=your_wp_username
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx
WP_POST_CATEGORY=


# Instagram Graph API (Optional / Meta Developer)
IG_ACCESS_TOKEN=EAAG...
IG_ACCOUNT_ID=178414...

# Storage Configuration (Optional)
# DATA_DIR=/path/to/custom/data

# Collage Configuration (Optional)
MAX_EVENTS_PER_ROW=4
```

> **Note on WordPress:** `WP_APP_PASSWORD` must be generated in WordPress Admin under **Users > Profile > Application Passwords**, not your primary login password. It must also have no spaces.
>
> **Note on Telegram Channel:** The bot **must be added as an Administrator** in the public channel with permissions to read, send, and delete messages.


---

## Running the Application

Start the continuous listener and scheduler:

```bash
python3 main.py
```

---

## Telegram Commands & Workflow

### 1. New Event Flow
- **Channel Ingestion:** Admins post an announcement text with a picture to the public channel (`PUBLIC_CHANNEL_ID`).
- **Deferred Auto-Interception:** The bot parses the content via Gemini AI first. If confirmed as an event, it deletes the raw post from the public channel and routes it to admin review; if it is not an event, it is preserved in the channel.
- **Admin Review:** The parsed event is forwarded to `ADMIN_CHAT_ID` with buttons: `[Publish]`, `[Discard]`, `[Cancel]`.
- **Publishing:** Clicking `[Publish]` posts the officially formatted message with `[➕ Prenota] [👥 Lista] [➖ Annulla]` to the public channel and generates the Instagram Story graphic locally.
- **Manual Trigger:** In `ADMIN_CHAT_ID`, reply to any forwarded text/photo message with `/event_process` (or shortcut `/ep`).
- **AI Event Generation:** In `ADMIN_CHAT_ID`, send `/event_generate <istruzioni>` (or shortcut `/eg`) with informal instructions (e.g. `Catan e Wingspan, venerdì 10 ottobre 21:00, host Destard, 4 posti`). Gemini AI interprets the parameters, fetches official box images from BoardGameGeek, stitches a horizontal collage if multiple games are requested, generates a concise Italian description within Telegram's 1024-character caption limit, and sends the drafted event to admin review.

### 2. Live Seat Booking & Same-Day Conflict Warnings
- Users click `[➕ Prenota]` on a channel post or discussion group reply to reserve a seat (or see `[🚫 Esauriti]` if full).
- Clicks increment personal seat reservation count in SQLite.
- The post message dynamically updates (`Posti: X/Y` or `0/Y Completo`), and the bot sends a reply to the post announcing the reservation.
- Users click `[👥 Lista]` to open a private DM with the bot and view the full list of participants without spamming the group, or manually call `/event_subs <id>` (or `/subs <id>`, or `/event_subs_<id>`).
- **Same-Day Conflict Warning:** If a user reserves a seat on an event while already subscribed to another valid event (not cancelled or unsubscribed) scheduled for the same day, the bot processes the reservation normally and immediately posts a warning in the discussion chat. The warning tags the user, lists the conflicting event(s) with titles and direct message links, and reminds the user to release their seat from whichever event they decide not to attend.
- Users click `[➖ Annulla]` to release reserved seats.

### 3. Daily Recap Flow
- Runs automatically at **16:00** on Mondays, Wednesdays, Fridays, Saturdays, and Sundays (silent if no events are scheduled).
- **Manual Trigger:** Send `/recap_generate` (or shortcut `/rg`) in `ADMIN_CHAT_ID` (or `/recap_generate DD-MM-YYYY` / `/rg DD-MM-YYYY` for any target date). If there are no scheduled events for today (or the target date), the bot notifies the admin directly in `ADMIN_CHAT_ID` (`Nessun evento in programma per oggi.`) without generating an empty recap.
- **Recap Card & Collage:** The bot generates a horizontal image collage of all scheduled games and compiles the formatted Italian recap text (using slim fallback if >1024 characters).
- **Review:** Admin reviews the collage and recap in Telegram with `[Publish Recap]` or `[Discard Recap]`.
- **Publishing:** Clicking `[Publish Recap]` sends the recap message to the public channel, renders the recap Instagram Story, uploads images to WordPress, and creates a draft blog post.
- **WordPress One-Click Live:** The bot returns the WordPress edit URL and a `[Pubblica su WordPress]` button to publish the post live immediately.

### 4. Admin Event Editing (Reply Commands)
In `ADMIN_CHAT_ID`, reply to any event announcement message (pending or already published) to update fields live in SQLite and edit the message in the channel:
- `/event_edit_title <Titolo>`
- `/event_edit_date <DD-MM-YYYY [HH:MM] o DD/MM/YYYY [HH:MM]>` (calcola automaticamente il giorno della settimana in italiano e sincronizza sia `date` che `normalized_date`)
- `/event_edit_system <Sistema/Gioco>`
- `/event_edit_host <Master o Host>`
- `/event_edit_type <rpg o boardgame>` (cambia la tipologia dell'evento tra Gioco di Ruolo con 'Master' o Gioco da Tavolo con 'Host')
- `/event_edit_seats <X/Y, numero intero, oppure null>` (`X/Y` imposta posti liberi/totali; un intero imposta il totale mantenendo le prenotazioni; `null`, `nessuno`, `illimitati`, `unlimited`, `none` o `0` rendono i posti illimitati, mostrati come `no limit`)
- `/event_edit_booked <numero intero>`
- `/event_edit_extra <Difficoltà, avvertenze, tag, oppure null per rimuovere>`
- `/event_edit_description <Descrizione o sinossi>`
- `/event_edit_image` (allega una nuova foto o album in risposta alla scheda evento, oppure rispondi a una foto con `/event_edit_image <event_id>`)
- `/event_regenerate_story` (o `/ers`): rigenera e invia in chat l'immagine della storia Instagram per l'evento risposto o per ID specificato

*Nota sui controlli di validità della data:*
Durante l'acquisizione iniziale dell'evento da parte dell'AI, il bot esegue un controllo automatico di sanità della data: se la data rilevata è nel passato oppure c'è una discrepanza tra il giorno della settimana scritto e quello effettivo di calendario (es. "Sabato 04 Settembre 2026" quando il 4 settembre è venerdì), viene anteposto un avviso visibile (`🚨 ATTENZIONE ANOMALIE DATA`) nel messaggio di revisione admin. Correggendo la data con `/event_edit_date`, l'avviso viene automaticamente rimosso.

### 5. Admin Subscriber Management
In `ADMIN_CHAT_ID`, each event card includes a `[👥 Gestisci Iscritti]` button:
- View current subscribers and seat counts.
- `➕` and `➖` buttons per subscriber to adjust seats or remove bookings.
- `[➕ Aggiungi Iscritto]` button to register any Telegram user via username.
- Commands (send standalone or in reply to an event):
  - `/event_sub_add <event_id> @username [posti]`
  - `/event_sub_remove <event_id> @username [posti]`
- **Public Group Notifications:** Whenever an event admin adds or removes subscribers or seats for a public event (via buttons, reply prompt, or commands), a notification is sent to the public discussion group (`DISCUSSION_GROUP_ID`) specifying that the modification was performed by an **event admin** (distinguishing event admins from group/server admins) and indicating the target user and seat count.

### 6. Event Cancellation & Reactivation
- **Cancellation (`[❌ Annulla Evento]`):** Updates status to `cancelled`, removes booking buttons from channel and discussion group, and posts a notification in the public discussion group (`DISCUSSION_GROUP_ID`) tagging all subscribed users to inform them of the cancellation (or sends a general notice if there are no subscribers).
- **Reactivation (`[♻️ Riattiva Evento]`):** Under a cancelled event in `ADMIN_CHAT_ID`, admins can click `[♻️ Riattiva Evento]`. This restores status to `approved`, restores booking buttons in the public channel and discussion group, and posts a notification in the discussion group notifying the original subscribers that the event is reactivated.


### 7. Event Overview & Bot Control Commands
- `/event_next`: Public command displaying today's and upcoming events in chronological order, with quick links to message, discussion chat, direct participant list deep links, and free/total seats counter. Accessible by any user in 1-on-1 private chat with the bot, via deep link (`t.me/{bot_username}?start=event_next`), in `ADMIN_CHAT_ID`, and in `DISCUSSION_GROUP_ID` (can be disabled in the discussion group via `ALLOW_GROUP_EVENT_NEXT=false` to prevent spam).
- `/event_subs <id>` (or `/subs <id>` / `/event_subs_<id>`): Public command to check the participant list for an event by ID.

In `ADMIN_CHAT_ID` only:
- `/event_repost <DATE> <SEATS>`: Repost an event with updated date and seats in a single step (supports calendar dates, `oggi`, and next weekday shortcuts `LUN`, `MER`, `VEN`). `SEATS` uses the same syntax as `/event_edit_seats` (`X/Y`, an integer, or `null`/`illimitati` for unlimited).
- `/event_schedule [ID] [DATA HH:MM]`: Set up recurring reposting schedule via opening days checkbox buttons (`Lunedì`, `Mercoledì`, `Venerdì`, `Sabato`, `Domenica`) or schedule a specific date.
- `/event_schedule_invoke <ID>`: Prepares and sends the approval card for a scheduled event for today's reposting.
- `/event_schedule_update <ID>`: In response to a new event post, overwrites the stored template of the specified scheduled event.
- `/event_schedule_list`: Lists all events scheduled for reposting with their IDs and clickable `/event_schedule_invoke` commands.
- `/bot_pause`: Pauses public channel monitoring (bot becomes "blind" and will not intercept or delete events posted to the channel).
- `/bot_resume`: Resumes public channel monitoring.
- `/bot_status`: Checks whether the bot is currently active or paused.

---

## Storage & Folder Structure

Images and database records are categorized by the **scheduled event date** (`YYYY/MM/DD`):

```text
data/
├── 2026/
│   └── 09/
│       └── 09/
│           ├── event_123.jpg       # Original uploaded image
│           ├── story_123.jpg       # Generated 1080x1920 Story
│           ├── recap_09-09-2026.jpg # Stitched collage
│           └── recap_story_09-09-2026.jpg # Recap Story
├── bot_database.db
├── Roboto-Bold.ttf
└── Roboto-Regular.ttf
```

---

## Maintenance & Diagnostic Scripts

All maintenance utilities are located in the `scripts/` directory:

- **Unzip Archived Images:**
  ```bash
  # Unzip all archives in a folder (year, month, or day):
  python3 scripts/unzip_images.py data/2026/09
  python3 scripts/unzip_images.py 2026/09

  # Unzip archives within a date range:
  python3 scripts/unzip_images.py --start 01-09-2026 --end 10-09-2026

  # Unzip for a specific date:
  python3 scripts/unzip_images.py --date 04-09-2026

  # Optionally delete the zip file after extraction:
  python3 scripts/unzip_images.py data/2026/09 --delete-zip
  ```

- **Manually Generate Instagram Story:**
  ```bash
  # Generate story image for event with ID 1:
  python3 scripts/generate_story.py 1

  # List all available events in the database:
  python3 scripts/generate_story.py --list

  # Generate story image and send it to the Telegram Admin Chat:
  python3 scripts/generate_story.py 1 --send-telegram

  # Generate story image with a custom output directory:
  python3 scripts/generate_story.py 1 --output-dir /path/to/custom_dir

  # Generate story image overriding the event photo:
  python3 scripts/generate_story.py 1 --image /path/to/image.jpg

  # Generate story image and publish directly to Instagram (via WordPress media upload):
  python3 scripts/generate_story.py 1 --publish-ig
  ```

- **Fix / Synchronize Inline Keyboards:**
  ```bash
  # Synchronize keyboards across approved event messages (Channel, Discussion, Admin):
  python3 scripts/fix_event_keyboards.py

  # Synchronize all statuses (including cancelled and pending):
  python3 scripts/fix_event_keyboards.py --status all

  # Fix keyboards for a single event by ID:
  python3 scripts/fix_event_keyboards.py --event-id 42

  # Fix events from a specific ID onwards:
  python3 scripts/fix_event_keyboards.py --since-id 30

  # Simulate without modifying messages (dry-run):
  python3 scripts/fix_event_keyboards.py --dry-run
  ```
  Synchronizes inline callback buttons (`book_{id}`, `unbook_{id}`, `start=subs_{id}`, `manage_subs_{id}`) across Telegram channel posts, discussion replies, and admin messages to match their current database IDs (processes approved events by default).


- **Reset Database & Clean Images:**
  ```bash
  python3 scripts/clean_db.py
  ```
  Safely truncates `events` and `reservations` tables, resets autoincrement counters, and removes generated `.jpg` files across all date folders while preserving fonts.

- **Check Meta Instagram Token:**
  ```bash
  python3 scripts/test_ig.py
  ```
  Tests connectivity and permissions of `IG_ACCESS_TOKEN` against Meta Graph API.

---

## Development & Tests

- **Code layout:** the `bot/` code is split into packages:
  - `bot/handlers/`: one module per command family (`control`, `public`, `ingestion`, `albums`, `extraction`, `edit`, `subscribers`, `recap`, `repost`, `repost_schedule`).
  - `bot/callbacks/`: inline-button handlers, dispatched by the `CALLBACK_ROUTES` prefix table in `router.py`.
  - `bot/service/`: shared Telegram side effects (post sync, booking, notices).
  - `bot/event_generator/`: the `/event_generate` feature.
  - `bot/common/`: shared helpers (`@admin_only`, seat parsing, media downloads, HTML/reply fallbacks, admin preview cards).
  - Runtime state lives in `bot/state.py`.
  - `core/` holds the services:
    - `core/db/`: SQLite data access, imported as `from core.db import ...`.
    - `core/scheduler/`: the APScheduler jobs (recap, archiving, repost digest) plus `runner.py`.
    - `core/wordpress/`: the WordPress REST client, imported as `from core.wordpress import ...`.
    - `ai_parser.py` (Gemini), `instagram.py`, `log_utils.py` and `config.py`.
  - Modules read settings at call time via `core.config`. Tests patch `core.config.*` for settings (including `DB_PATH` for a temporary database) and the *using* module for functions (e.g. `bot.handlers.extraction.parse_event_message`).
  - See `GEMINI.md` §3.1 (`bot/`) and §3.2 (`core/`) for details.
- **Running the test suite:**
  ```bash
  pip install pytest
  python3 -m pytest tests
  ```
