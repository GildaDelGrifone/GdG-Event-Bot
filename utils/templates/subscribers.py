"""Subscriber display, participants list, subscriber commands and the management panel."""
import html

from utils.templates.common import EVENTBRITE_ROW_PREFIX, format_event_title_link


def format_reservation_subscriber_display(reservation, as_html=True):
    """
    Returns the display string for a subscriber in a reservation.
    - Eventbrite bookings are always '🎟️ {name}' (they have no Telegram identity).
    - If a valid Telegram username exists, returns '@username'.
    - If user has no username:
      - If as_html=True and user_id exists: returns '<a href="tg://user?id={user_id}">{name}</a>'
      - If as_html=False or no user_id: returns '{name}' (or 'ID:{user_id}')
    """
    if reservation.get('source') == 'eventbrite':
        name = (reservation.get('full_name') or '').strip() or "Partecipante Eventbrite"
        return f"{EVENTBRITE_ROW_PREFIX}{html.escape(name) if as_html else name}"

    uname = (reservation.get('username') or '').strip()
    fname = (reservation.get('full_name') or '').strip()
    uid = reservation.get('user_id')

    # If username contains spaces, it was a display name stored previously in the username column
    if uname and " " in uname and not fname:
        fname = uname
        uname = ""

    # Clean username if present
    clean_uname = uname.lstrip('@') if uname else ""

    if clean_uname:
        tag = f"@{clean_uname}"
        return html.escape(tag) if as_html else tag
    elif fname:
        if as_html and uid:
            return f'<a href="tg://user?id={uid}">{html.escape(fname)}</a>'
        return html.escape(fname) if as_html else fname
    elif uid:
        label = f"ID:{uid}"
        return label
    else:
        return "Utente"


def format_event_participants_message(event, reservations):
    event_display = format_event_title_link(event)
    booked = int(event.get('booked_seats', 0) or 0)
    max_s = event.get('max_seats')
    max_str = str(max_s) if max_s is not None else "Nessun limite"
    date = event.get('date') or ""
    status = event.get('status', 'approved')

    status_suffix = ""
    if status == "cancelled":
        status_suffix = " ❌ <i>[ANNULLATO]</i>"

    text = (
        f"📋 <b>Partecipanti all'evento</b>{status_suffix}\n"
        f"📌 {event_display}\n"
    )
    if date:
        text += f"🗓️ <i>{html.escape(date)}</i>\n"
    text += f"🪑 Posti occupati: <b>{booked}/{max_str}</b>\n\n"

    if not reservations:
        text += "<i>Nessun partecipante iscritto al momento.</i>\n"
    else:
        text += "<b>Elenco iscritti:</b>\n"
        for i, s in enumerate(reservations, 1):
            display_name = format_reservation_subscriber_display(s, as_html=True)
            seats = s.get('seats_booked', 1)
            posti_str = f" ({seats} posti)" if seats > 1 else ""
            text += f"{i}. <b>{display_name}</b>{posti_str}\n"

    return text


# The add prompt is matched by bot.handlers.subscribers.handle_admin_reply: keep the marker inside the prompt text
ADD_SUBSCRIBER_PROMPT_MARKER = "Invia l'username Telegram, rispondendo a questo messaggio, da aggiungere all'evento #"


SUBSCRIBERS_PANEL_TITLE = "Gestione Iscritti"


SUBSCRIBERS_PANEL_EMPTY = "<i>Nessun utente iscritto al momento.</i>\n"


SUBSCRIBERS_PANEL_LIST_HEADER = "<b>Iscritti:</b>\n"


SUBSCRIBERS_PANEL_EVENTBRITE_LEGEND = "\n🎟️ = prenotazione Eventbrite (gestisci dalla dashboard)\n"


SUBSCRIBER_EVENT_ID_NOT_INT = "L'ID evento deve essere un numero intero."


SUBSCRIBER_SEATS_NOT_INT = "I posti devono essere un numero intero."


def format_subscriber_usage_reply(command):
    return f"Uso in risposta a un evento: <code>{command} @username [posti]</code>"


def format_subscriber_usage(command):
    return (
        f"Uso: <code>{command} &lt;event_id&gt; @username [posti]</code>\n"
        f"Oppure rispondi a un evento con: <code>{command} @username [posti]</code>"
    )


def format_subscribers_panel(event, reservations):
    booked = int(event.get('booked_seats', 0) or 0)
    max_s = event.get('max_seats')
    max_str = str(max_s) if max_s is not None else "Nessun limite"

    text = (
        f"👥 <b>{SUBSCRIBERS_PANEL_TITLE}</b>\n"
        f"📌 {format_event_title_link(event)}\n"
        f"🪑 Posti occupati: <b>{booked}/{max_str}</b>\n\n"
    )

    if not reservations:
        text += SUBSCRIBERS_PANEL_EMPTY
    else:
        text += SUBSCRIBERS_PANEL_LIST_HEADER
        for i, res in enumerate(reservations, 1):
            seats = res.get('seats_booked', 1)
            posti_str = "posto" if seats == 1 else "posti"
            text += f"{i}. <b>{format_reservation_subscriber_display(res, as_html=True)}</b> — {seats} {posti_str}\n"

    if any(res.get('source') == 'eventbrite' for res in reservations):
        text += SUBSCRIBERS_PANEL_EVENTBRITE_LEGEND

    text += (
        f"\n<i>Modifica con i tasti sotto oppure invia:</i>\n"
        f"<code>/event_sub_add {event['id']} @username [posti]</code>\n"
        f"<code>/event_sub_remove {event['id']} @username [posti]</code>"
    )
    return text


def format_add_subscriber_prompt(event_id):
    return (
        f"✏️ {ADD_SUBSCRIBER_PROMPT_MARKER}{event_id} (es. <code>@mario</code> oppure <code>@mario 2</code>):\n"
        f"Oppure usa: <code>/event_sub_add {event_id} @username [posti]</code>"
    )
