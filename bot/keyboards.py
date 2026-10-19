from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from core.db import get_event
from core.eventbrite import attendees_dashboard_url, dashboard_url, eventbrite_enabled
from utils.templates import EVENTBRITE_ROW_PREFIX, format_reservation_subscriber_display

# (callback key, Italian day name) for the repost schedule toggles, in display order
SCHEDULE_DAYS = (
    ("lun", "Lunedì"),
    ("mer", "Mercoledì"),
    ("ven", "Venerdì"),
    ("sab", "Sabato"),
    ("dom", "Domenica"),
)
SCHEDULE_DAY_NAMES = dict(SCHEDULE_DAYS)


def _manage_subs_button(event_id):
    return InlineKeyboardButton("👥 Gestisci Iscritti", callback_data=f"manage_subs_{event_id}")


def get_approval_keyboard(event_id):
    rows = [
        [
            InlineKeyboardButton("Publish", callback_data=f"publish_event_{event_id}"),
            InlineKeyboardButton("Discard", callback_data=f"discard_event_{event_id}"),
        ],
    ]
    if eventbrite_enabled():
        rows.append([InlineKeyboardButton("🚀 Publish + Eventbrite", callback_data=f"publish_eb_event_{event_id}")])
    rows.append([_manage_subs_button(event_id)])
    return InlineKeyboardMarkup(rows)


def get_approved_event_keyboard(event_id, event=None):
    rows = [[
        InlineKeyboardButton("❌ Annulla Evento", callback_data=f"cancel_event_{event_id}"),
        _manage_subs_button(event_id),
    ]]
    if eventbrite_enabled():
        if event and event.get('eventbrite_event_id'):
            rows.append([InlineKeyboardButton("🎟️ Eventbrite", url=dashboard_url(event['eventbrite_event_id']))])
        else:
            rows.append([InlineKeyboardButton("🎟️ Pubblica su Eventbrite", callback_data=f"eb_publish_{event_id}")])
    return InlineKeyboardMarkup(rows)


def get_cancelled_event_keyboard(event_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("♻️ Riattiva Evento", callback_data=f"reactivate_event_{event_id}"),
        _manage_subs_button(event_id),
    ]])


def get_subscribers_management_keyboard(event_id, reservations, event=None):
    keyboard = []
    for res in reservations:
        if res.get('source') == 'eventbrite':
            # Managed on Eventbrite: a single button that opens the attendee dashboard instead of ± seats
            name = (res.get('full_name') or '').strip() or "Partecipante"
            name = name if len(name) <= 12 else name[:11] + "…"
            eb_event_id = (event or {}).get('eventbrite_event_id')
            if eb_event_id:
                keyboard.append([InlineKeyboardButton(
                    f"{EVENTBRITE_ROW_PREFIX}{name} ({res.get('seats_booked', 1)})", url=attendees_dashboard_url(eb_event_id)
                )])
            continue
        label = format_reservation_subscriber_display(res, as_html=False)
        label = label if len(label) <= 12 else label[:11] + "…"
        seats = res.get('seats_booked', 1)
        res_id = res['id']
        keyboard.append([
            InlineKeyboardButton(f"➖ {label} ({seats})", callback_data=f"sub_dec_{event_id}_{res_id}"),
            InlineKeyboardButton(f"➕ {label} ({seats})", callback_data=f"sub_inc_{event_id}_{res_id}"),
        ])
    keyboard.append([InlineKeyboardButton("➕ Aggiungi Iscritto", callback_data=f"sub_addnew_{event_id}")])
    keyboard.append([
        InlineKeyboardButton("🔄 Aggiorna", callback_data=f"manage_subs_{event_id}"),
        InlineKeyboardButton("❌ Chiudi", callback_data=f"close_subs_{event_id}"),
    ])
    return InlineKeyboardMarkup(keyboard)


def get_recap_approval_keyboard(date_str):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Publish Recap", callback_data=f"publish_recap_{date_str}"),
        InlineKeyboardButton("Discard Recap", callback_data=f"discard_recap_{date_str}"),
    ]])


def get_wp_publish_keyboard(post_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Pubblica su WordPress", callback_data=f"publish_wp_{post_id}"),
    ]])


def is_event_full(event):
    if not event:
        return False
    max_seats = event.get('max_seats')
    booked_seats = int(event.get('booked_seats', 0) or 0)
    return max_seats is not None and booked_seats >= int(max_seats)


def get_event_booking_keyboard(event_id, event=None, bot_username=None):
    if event is None:
        event = get_event(event_id)

    if is_event_full(event):
        row = [InlineKeyboardButton("🚫 Esauriti", callback_data=f"full_{event_id}")]
    else:
        row = [InlineKeyboardButton("➕ Prenota", callback_data=f"book_{event_id}")]

    if bot_username is None:
        bot_username = config.TELEGRAM_BOT_USERNAME
    if bot_username:
        clean_username = bot_username.lstrip('@')
        row.append(InlineKeyboardButton("👥 Lista", url=f"https://t.me/{clean_username}?start=subs_{event_id}"))

    row.append(InlineKeyboardButton("➖ Annulla", callback_data=f"unbook_{event_id}"))
    return InlineKeyboardMarkup([row])


def get_schedule_repost_keyboard(scheduled_id, active_days=None):
    active_lower = {str(d).strip().lower() for d in (active_days or [])}

    def day_button(key, name):
        icon = "✅" if key in active_lower or name.lower() in active_lower else "⬜"
        return InlineKeyboardButton(f"{icon} {name}", callback_data=f"sched_toggle_{scheduled_id}_{key}")

    day_buttons = [day_button(key, name) for key, name in SCHEDULE_DAYS]
    return InlineKeyboardMarkup([
        day_buttons[:3],
        day_buttons[3:],
        [
            InlineKeyboardButton("🗑️ Elimina", callback_data=f"sched_del_{scheduled_id}"),
            InlineKeyboardButton("❌ Chiudi", callback_data=f"sched_close_{scheduled_id}"),
        ],
    ])
