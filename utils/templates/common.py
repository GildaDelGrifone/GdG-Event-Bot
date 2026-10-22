"""Shared fragments and generic replies used across the bot."""
import html


ASSOCIATION_ADDRESS = "Gilda del Grifone, Via Ada Negri 8/A, Torino"


EVENTBRITE_ROW_PREFIX = "🎟️ "


def format_event_title_link(event):
    if not event:
        return "<b>Evento</b>"
    event_title = event.get('title') or 'Evento'
    escaped_title = html.escape(event_title)
    link = event.get('message_link')
    if link:
        return f'<a href="{link}"><b>{escaped_title}</b></a>'
    return f'<b>{escaped_title}</b>'


UNAUTHORIZED_REPLY = "Non sei autorizzato."


POPUP_EVENT_NOT_FOUND = "Evento non trovato."


POPUP_CLOSED = "Chiuso."


def format_event_id_not_found(event_id):
    return f"❌ Evento #{event_id} non trovato"


def format_event_id_not_found_in_db(event_id):
    return f"❌ Evento #{event_id} non trovato nel database."


NO_TEXT_IN_REPLIED_MESSAGE = "❌ Nessun testo trovato nel messaggio risposto."


def format_admin_failure(message):
    return f"❌ {message}"


def format_admin_success(message):
    return f"✅ {message}"


def format_seats_count(count):
    return f"{count} posto" if count == 1 else f"{count} posti"
