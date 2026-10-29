"""Inline keyboard labels and button formatters."""

from utils.templates.common import EVENTBRITE_ROW_PREFIX


BUTTON_EB_RETRY_LOGO = "🖼️ Riprova caricamento logo"


BUTTON_EB_RECREATE = "🎟️ Ricrea su Eventbrite"


BUTTON_EB_DASHBOARD = "🎟️ Apri dashboard Eventbrite"


BUTTON_EB_CANCEL_DONE = "🔁 Ho annullato tutto, completa"


def format_eb_order_button(name, seats):
    return f"❌ {name} ({seats})"


BUTTON_MANAGE_SUBS = "👥 Gestisci Iscritti"


BUTTON_CLOSE = "❌ Chiudi"


BUTTON_PUBLISH = "Publish"


BUTTON_DISCARD = "Discard"


BUTTON_PUBLISH_TELEGRAM_AND_EB = "🚀 Telegram + EB"


BUTTON_PUBLISH_EB_ONLY = "🎟️ Solo Eventbrite"


BUTTON_PUBLISH_PLUS_EB = "🚀 Publish + Eventbrite"


BUTTON_CANCEL_EVENT = "❌ Annulla Evento"


BUTTON_EB_PUBLISH = "🎟️ Pubblica su Eventbrite"


BUTTON_EB_DASHBOARD_LINK = "🎟️ Eventbrite"


BUTTON_EB_CANCEL = "🚫 Annulla su Eventbrite"


BUTTON_EB_COMPLETE_CANCEL = "🔁 Completa annullamento"


BUTTON_EB_CONFIRM_CANCEL = "✅ Sì, annulla su EB"


BUTTON_BACK = "↩️ Indietro"


BUTTON_CONFIRM_CANCEL = "✅ Sì, annulla"


BUTTON_REACTIVATE = "♻️ Riattiva Evento"


BUTTON_ADD_SUBSCRIBER = "➕ Aggiungi Iscritto"


BUTTON_REFRESH = "🔄 Aggiorna"


BUTTON_PUBLISH_RECAP = "Publish Recap"


BUTTON_DISCARD_RECAP = "Discard Recap"


BUTTON_PUBLISH_WORDPRESS = "Pubblica su WordPress"


BUTTON_PUBLISH_ASTRO = "Pubblica sul sito"


BUTTON_DISCARD_ARTICLE = "🗑️ Scarta articolo"


BUTTON_FULL = "🚫 Esauriti"


BUTTON_BOOK = "➕ Prenota"


BUTTON_LIST = "👥 Lista"


BUTTON_UNBOOK = "➖ Annulla"


BUTTON_DELETE = "🗑️ Elimina"


BUTTON_VENUE_DEFAULT_SUFFIX = " (predefinito)"


BUTTON_VENUE_SELECTED_PREFIX = "✅ "


SCHEDULE_DAY_ACTIVE_ICON = "✅"


SCHEDULE_DAY_INACTIVE_ICON = "⬜"


SUBSCRIBER_FALLBACK_NAME = "Partecipante"


def format_venue_button(name, selected, default):
    return (BUTTON_VENUE_SELECTED_PREFIX if selected else "") + name + (BUTTON_VENUE_DEFAULT_SUFFIX if default else "")


def format_schedule_day_button(name, active):
    return f"{SCHEDULE_DAY_ACTIVE_ICON if active else SCHEDULE_DAY_INACTIVE_ICON} {name}"


def format_schedule_advance_button(days):
    return f"⏳ Anticipo: {days} gg"


def format_decrement_seat_button(label, seats):
    return f"➖ {label} ({seats})"


def format_increment_seat_button(label, seats):
    return f"➕ {label} ({seats})"


def format_eventbrite_order_row_button(name, seats):
    return f"{EVENTBRITE_ROW_PREFIX}{name} ({seats})"
