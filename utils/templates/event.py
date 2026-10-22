"""Public event post, Instagram story and seat texts."""
import html


DISCUSSION_BOOKING_TEXT = "👇 Gestisci qui la tua prenotazione!"


def format_discussion_booking_message(event):
    """Text of the booking reply under the channel post in the discussion group (adds the Eventbrite link when live)."""
    if event and event.get('eventbrite_url') and event.get('eventbrite_status') == 'live':
        return f'{DISCUSSION_BOOKING_TEXT}\n🎟️ Prenota anche su Eventbrite: <a href="{html.escape(event["eventbrite_url"], quote=True)}">link</a>'
    return DISCUSSION_BOOKING_TEXT


def format_event_seats(event_data):
    booked = int(event_data.get('booked_seats', 0) or 0)
    max_s = event_data.get('max_seats')
    status = event_data.get('status', 'pending')

    if status == 'cancelled':
        if max_s is None:
            return "0 (Nessun limite) [ANNULLATO]"
        return f"0/{max_s} [ANNULLATO]"

    if max_s is None:
        if booked > 0:
            return f"Nessun limite (Prenotati: {booked})"
        return "Nessun limite"

    max_s = int(max_s)
    avail = max_s - booked
    if avail <= 0:
        return f"0/{max_s} Completo"
    return f"{avail}/{max_s}"


def format_public_event_message(event_data):
    status = event_data.get('status', 'pending')
    raw_title = event_data.get('title', 'Evento')
    escaped_title = html.escape(raw_title)

    posti = format_event_seats(event_data)
    if status == 'cancelled':
        title = f"❌ [ANNULLATO] {escaped_title}"
    else:
        title = f"{escaped_title}"
        
    extra = (event_data.get('extra_info') or '').strip()
    extra_block = f"\n🏷️ Dettagli:\n{html.escape(extra)}\n" if extra else ""

    desc = (event_data.get('description') or '').strip()
    desc_block = f"\n📝 {html.escape(desc)}" if desc else ""

    is_rp = bool(event_data.get('is_roleplay'))
    host_label = "Master" if is_rp else "Host"
    host = html.escape(str(event_data.get('host') or 'N/A'))
    system = html.escape(str(event_data.get('system') or 'N/A'))
    date = html.escape(str(event_data.get('date') or 'N/A'))

    return (
        f"📣 <b>{title}</b>\n"
        f"🗓️ Data: {date}\n"
        f"🎲 Sistema: {system}\n"
        f"👑 {host_label}: {host}\n"
        f"🪑 Posti: {posti}\n"
        f"{extra_block}"
        f"{desc_block}"
    )


def format_instagram_story(event_data):
    max_s = event_data.get('max_seats')
    
    if max_s is None:
        posti = "Nessun limite"
    else:
        posti = str(max_s)

    is_rp = bool(event_data.get('is_roleplay'))
    host_label = "Master" if is_rp else "Host"
    host = event_data.get('host') or 'N/A'
    extra = (event_data.get('extra_info') or '').strip()
    extra_block = f"\n🏷️ Dettagli:\n{extra}\n" if extra else ""
    desc = (event_data.get('description') or '').strip()
    desc_block = f"\n{desc}" if desc else ""

    return (
        f"Titolo: {event_data.get('title', 'N/A')}\n"
        f"Data: {event_data.get('date', 'N/A')}\n"
        f"Sistema: {event_data.get('system', 'N/A')}\n"
        f"{host_label}: {host}\n"
        f"Posti: {posti}\n"
        f"{extra_block}"
        f"{desc_block}"
    )
