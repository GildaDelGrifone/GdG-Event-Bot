from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from core.db import get_event
from core.eventbrite import dashboard_url, eventbrite_enabled, order_url
from bot.state import runtime_state
from utils.templates import (
    BUTTON_ADD_SUBSCRIBER, BUTTON_BACK, BUTTON_BOOK, BUTTON_CANCEL_EVENT, BUTTON_CLOSE, BUTTON_CONFIRM_CANCEL,
    BUTTON_DELETE, BUTTON_DISCARD, BUTTON_DISCARD_RECAP, BUTTON_EB_CANCEL, BUTTON_EB_COMPLETE_CANCEL,
    BUTTON_EB_CONFIRM_CANCEL, BUTTON_EB_DASHBOARD_LINK, BUTTON_EB_PUBLISH, BUTTON_EB_RECREATE, BUTTON_FULL,
    BUTTON_LIST, BUTTON_MANAGE_SUBS, BUTTON_PUBLISH, BUTTON_PUBLISH_EB_ONLY, BUTTON_PUBLISH_PLUS_EB,
    BUTTON_PUBLISH_RECAP, BUTTON_PUBLISH_TELEGRAM_AND_EB, BUTTON_PUBLISH_WORDPRESS, BUTTON_REACTIVATE, BUTTON_REFRESH,
    BUTTON_UNBOOK, SUBSCRIBER_FALLBACK_NAME, format_decrement_seat_button,
    format_eventbrite_order_row_button, format_increment_seat_button, format_reservation_subscriber_display,
    format_schedule_day_button, format_venue_button,
)

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
    return InlineKeyboardButton(BUTTON_MANAGE_SUBS, callback_data=f"manage_subs_{event_id}")


def get_venue_keyboard(venues, current_id, default_id):
    """One button per venue; `venues` is [(id, name)], the venue in use is marked ✅ and the default tagged."""
    rows = []
    for venue_id, name in venues:
        label = format_venue_button(name, venue_id == current_id, venue_id == default_id)
        rows.append([InlineKeyboardButton(label, callback_data=f"ebvenue_{venue_id}")])
    rows.append([InlineKeyboardButton(BUTTON_CLOSE, callback_data="ebvenue_close")])
    return InlineKeyboardMarkup(rows)


def get_approval_keyboard(event_id):
    publish = InlineKeyboardButton(BUTTON_PUBLISH, callback_data=f"publish_event_{event_id}")
    discard = InlineKeyboardButton(BUTTON_DISCARD, callback_data=f"discard_event_{event_id}")
    eventbrite_only = eventbrite_enabled() and runtime_state.eventbrite_only  # /bot_eventbrite_only_toggle
    rows = [[discard] if eventbrite_only else [publish, discard]]
    if eventbrite_only:
        rows.append([
            InlineKeyboardButton(BUTTON_PUBLISH_TELEGRAM_AND_EB, callback_data=f"publish_eb_event_{event_id}"),
            InlineKeyboardButton(BUTTON_PUBLISH_EB_ONLY, callback_data=f"publish_eb_only_{event_id}"),
        ])
    elif eventbrite_enabled():
        rows.append([InlineKeyboardButton(BUTTON_PUBLISH_PLUS_EB, callback_data=f"publish_eb_event_{event_id}")])
    rows.append([_manage_subs_button(event_id)])
    return InlineKeyboardMarkup(rows)


def get_approved_event_keyboard(event_id, event=None):
    rows = [[
        InlineKeyboardButton(BUTTON_CANCEL_EVENT, callback_data=f"cancel_event_{event_id}"),
        _manage_subs_button(event_id),
    ]]
    if eventbrite_enabled():
        if event and event.get('eventbrite_event_id'):
            rows.append(_eventbrite_row(event_id, event))
        else:
            rows.append([InlineKeyboardButton(BUTTON_EB_PUBLISH, callback_data=f"eb_publish_{event_id}")])
    return InlineKeyboardMarkup(rows)


def _eventbrite_row(event_id, event):
    """Dashboard link plus the Eventbrite-only action that fits the current Eventbrite state."""
    row = [InlineKeyboardButton(BUTTON_EB_DASHBOARD_LINK, url=dashboard_url(event['eventbrite_event_id']))]
    status = event.get('eventbrite_status')
    if status in ('live', 'unpublished'):
        row.append(InlineKeyboardButton(BUTTON_EB_CANCEL, callback_data=f"eb_cancel_ask_{event_id}"))
    elif status == 'closed':
        row.append(InlineKeyboardButton(BUTTON_EB_COMPLETE_CANCEL, callback_data=f"eb_cancel_retry_{event_id}"))
    elif status == 'canceled':
        row.append(InlineKeyboardButton(BUTTON_EB_RECREATE, callback_data=f"eb_recreate_{event_id}"))
    return row


def get_eventbrite_cancel_confirmation_keyboard(event_id):
    """Confirmation for [🚫 Annulla su Eventbrite]: cancels only the Eventbrite event, Telegram stays active."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(BUTTON_EB_CONFIRM_CANCEL, callback_data=f"eb_cancel_do_{event_id}"),
        InlineKeyboardButton(BUTTON_BACK, callback_data=f"cancel_abort_{event_id}"),
    ]])


def get_cancel_confirmation_keyboard(event_id):
    """Shown in place of the approved-card buttons after [❌ Annulla Evento], so a misclick cannot cancel an event."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(BUTTON_CONFIRM_CANCEL, callback_data=f"cancel_confirm_{event_id}"),
        InlineKeyboardButton(BUTTON_BACK, callback_data=f"cancel_abort_{event_id}"),
    ]])


def get_cancelled_event_keyboard(event_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(BUTTON_REACTIVATE, callback_data=f"reactivate_event_{event_id}"),
        _manage_subs_button(event_id),
    ]])


def get_subscribers_management_keyboard(event_id, reservations, event=None):
    keyboard = []
    for res in reservations:
        if res.get('source') == 'eventbrite':
            # Managed on Eventbrite: a single button that opens the order's page instead of ± seats
            name = (res.get('full_name') or '').strip() or SUBSCRIBER_FALLBACK_NAME
            name = name if len(name) <= 12 else name[:11] + "…"
            if res.get('eventbrite_order_id'):
                keyboard.append([InlineKeyboardButton(
                    format_eventbrite_order_row_button(name, res.get('seats_booked', 1)), url=order_url(res['eventbrite_order_id'])
                )])
            continue
        label = format_reservation_subscriber_display(res, as_html=False)
        label = label if len(label) <= 12 else label[:11] + "…"
        seats = res.get('seats_booked', 1)
        res_id = res['id']
        keyboard.append([
            InlineKeyboardButton(format_decrement_seat_button(label, seats), callback_data=f"sub_dec_{event_id}_{res_id}"),
            InlineKeyboardButton(format_increment_seat_button(label, seats), callback_data=f"sub_inc_{event_id}_{res_id}"),
        ])
    keyboard.append([InlineKeyboardButton(BUTTON_ADD_SUBSCRIBER, callback_data=f"sub_addnew_{event_id}")])
    keyboard.append([
        InlineKeyboardButton(BUTTON_REFRESH, callback_data=f"manage_subs_{event_id}"),
        InlineKeyboardButton(BUTTON_CLOSE, callback_data=f"close_subs_{event_id}"),
    ])
    return InlineKeyboardMarkup(keyboard)


def get_recap_approval_keyboard(date_str):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(BUTTON_PUBLISH_RECAP, callback_data=f"publish_recap_{date_str}"),
        InlineKeyboardButton(BUTTON_DISCARD_RECAP, callback_data=f"discard_recap_{date_str}"),
    ]])


def get_wp_publish_keyboard(post_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(BUTTON_PUBLISH_WORDPRESS, callback_data=f"publish_wp_{post_id}"),
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
        row = [InlineKeyboardButton(BUTTON_FULL, callback_data=f"full_{event_id}")]
    else:
        row = [InlineKeyboardButton(BUTTON_BOOK, callback_data=f"book_{event_id}")]

    if bot_username is None:
        bot_username = config.TELEGRAM_BOT_USERNAME
    if bot_username:
        clean_username = bot_username.lstrip('@')
        row.append(InlineKeyboardButton(BUTTON_LIST, url=f"https://t.me/{clean_username}?start=subs_{event_id}"))

    row.append(InlineKeyboardButton(BUTTON_UNBOOK, callback_data=f"unbook_{event_id}"))
    return InlineKeyboardMarkup([row])


def get_schedule_repost_keyboard(scheduled_id, active_days=None):
    active_lower = {str(d).strip().lower() for d in (active_days or [])}

    def day_button(key, name):
        active = key in active_lower or name.lower() in active_lower
        return InlineKeyboardButton(format_schedule_day_button(name, active), callback_data=f"sched_toggle_{scheduled_id}_{key}")

    day_buttons = [day_button(key, name) for key, name in SCHEDULE_DAYS]
    return InlineKeyboardMarkup([
        day_buttons[:3],
        day_buttons[3:],
        [
            InlineKeyboardButton(BUTTON_DELETE, callback_data=f"sched_del_{scheduled_id}"),
            InlineKeyboardButton(BUTTON_CLOSE, callback_data=f"sched_close_{scheduled_id}"),
        ],
    ])
