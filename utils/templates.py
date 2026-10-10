import html

def format_event_title_link(event):
    if not event:
        return "<b>Evento</b>"
    event_title = event.get('title') or 'Evento'
    escaped_title = html.escape(event_title)
    link = event.get('message_link')
    if link:
        return f'<a href="{link}"><b>{escaped_title}</b></a>'
    return f'<b>{escaped_title}</b>'

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

def recap_generate_text(day_str, date_str, events):
    header = (
        f"Quali sono le proposte della Gilda del Grifone per stasera, {day_str} {date_str}? 🎲\n\n"
        f"Ecco i tavoli in programma! Trovi i link per prenotarti nei commenti qui sotto:\n\n"
    )
    
    body = ""
    for ev in events:
        sys_val = ev.get('system')
        sys_str = f" ({html.escape(sys_val)})" if sys_val else ""
        
        booked = int(ev.get('booked_seats', 0) or 0)
        max_s = ev.get('max_seats')
        
        if max_s is None:
            seats_display = f"Nessun limite (Prenotati: {booked})"
        else:
            max_s = int(max_s)
            avail = max_s - booked
            if avail <= 0:
                seats_display = f"0/{max_s} Completo"
            else:
                seats_display = f"{avail}/{max_s}"
            
        title = html.escape(ev.get('title') or 'Evento')
            
        if ev.get('status') == 'cancelled':
            if max_s is None:
                seats_display = "0 (Nessun limite)"
            else:
                seats_display = f"0/{max_s}"
            body += f"- ❌ <b>{title}</b>{sys_str} : {seats_display} [ANNULLATO]\n\n"
        else:
            body += f"- <b>{title}</b>{sys_str} : {seats_display}\n\n"
        
    footer = (
        "Tutto pieno? Vieni lo stesso! Abbiamo oltre 400 giochi a disposizione. "
        "Se invece vuoi proporre tu una serata, contatta @Destard o @ManueleAbi.\n\n"
        "Ci vediamo alle 20:45! 🦅"
    )
    
    full_text = header + body + footer
    
    if len(full_text) > 1024:
        slim_header = (
            f"Proposte di stasera, {day_str} {date_str} 🎲\n"
            f"Trovi i link per prenotarti nei commenti qui sotto:\n\n"
        )
        slim_footer = (
            "\nVuoi proporre una serata? Scrivi a @Destard o @ManueleAbi.\n"
            "Ci vediamo alle 20:45! 🦅"
        )
        return slim_header + body + slim_footer
        
    return full_text



def recap_links_text(events):
    if not events:
        return ""
    text = "🔗 <b>Link agli eventi per prenotarsi:</b>\n\n"
    for ev in events:
        if ev.get('status') == 'cancelled':
            continue
        title_display = format_event_title_link(ev)
        sys_val = ev.get('system')
        sys_str = f" ({html.escape(sys_val)})" if sys_val else ""
        text += f"- {title_display}{sys_str}\n"
    return text


def format_reservation_subscriber_display(reservation, as_html=True):
    """
    Returns the display string for a subscriber in a reservation.
    - If a valid Telegram username exists, returns '@username'.
    - If user has no username:
      - If as_html=True and user_id exists: returns '<a href="tg://user?id={user_id}">{name}</a>'
      - If as_html=False or no user_id: returns '{name}' (or 'ID:{user_id}')
    """
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


def format_schedule_repost_message(scheduled_event):
    sched_id = scheduled_event['id']
    title = scheduled_event.get('title') or "Evento"
    days = scheduled_event.get('schedule_days') or []
    days_str = ", ".join(days) if days else "Nessuno (seleziona con i pulsanti sotto)"
    spec_date = scheduled_event.get('specific_date') or "Nessuna data specifica"

    return (
        f"📅 <b>Programmazione Repost Evento #{sched_id}</b>\n"
        f"🏷️ <b>Titolo:</b> {html.escape(title)}\n\n"
        f"🗓️ <b>Giorni settimanali attivi:</b> {days_str}\n"
        f"📌 <b>Data specifica impostata:</b> {spec_date}\n\n"
        f"Tocca i pulsanti in basso per attivare/disattivare i giorni in cui ripubblicare l'evento.\n\n"
        f"👉 Per programmare una data specifica (stessa sintassi di /event_edit_date):\n"
        f"<code>/event_schedule {sched_id} DD-MM-YYYY [HH:MM]</code>\n"
        f"(es. <code>/event_schedule {sched_id} 09-10-2026 21:00</code>)"
    )

REPOST_UPDATE_REMINDER = (
    "💡 <i>Promemoria:</i> Puoi aggiornare il contenuto di un evento programmato rispondendo a un messaggio con il nuovo testo/locandina e usando:\n"
    "<code>/event_schedule_update ID</code>"
)
