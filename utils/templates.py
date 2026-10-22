import html

ASSOCIATION_ADDRESS = "Gilda del Grifone, Via Ada Negri 8/A, Torino"
EVENTBRITE_ROW_PREFIX = "🎟️ "
DISCUSSION_BOOKING_TEXT = "👇 Gestisci qui la tua prenotazione!"

def format_event_title_link(event):
    if not event:
        return "<b>Evento</b>"
    event_title = event.get('title') or 'Evento'
    escaped_title = html.escape(event_title)
    link = event.get('message_link')
    if link:
        return f'<a href="{link}"><b>{escaped_title}</b></a>'
    return f'<b>{escaped_title}</b>'

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


# ---------------------------------------------------------------------------
# Generic replies
# ---------------------------------------------------------------------------
UNAUTHORIZED_REPLY = "Non sei autorizzato."
POPUP_EVENT_NOT_FOUND = "Evento non trovato."
POPUP_CLOSED = "Chiuso."


def format_event_id_not_found(event_id):
    return f"❌ Evento #{event_id} non trovato"


def format_event_id_not_found_in_db(event_id):
    return f"❌ Evento #{event_id} non trovato nel database."


# ---------------------------------------------------------------------------
# Bot control (/bot_pause, /bot_resume, /bot_status, Eventbrite-only mode, venue)
# ---------------------------------------------------------------------------
BOT_PAUSED_TEXT = "🔴 **Bot in pausa!**\nIl bot ora ignorerà tutti i messaggi inviati sul canale eventi."
BOT_RESUMED_TEXT = "🟢 **Bot riattivato!**\nIl bot ricomincerà a monitorare il canale eventi."
EVENTBRITE_ONLY_UNAVAILABLE_TEXT = "❌ Eventbrite non è configurato: la modalità solo Eventbrite non è disponibile."
EVENTBRITE_ONLY_ON_TEXT = ("🎟️ Modalità solo Eventbrite ATTIVA: la scheda dei nuovi eventi mostra solo i pulsanti Eventbrite "
                           "e la storia Instagram non viene generata.")
EVENTBRITE_ONLY_OFF_TEXT = "📣 Modalità solo Eventbrite DISATTIVATA: pulsanti Telegram e storia Instagram di nuovo attivi."
EVENTBRITE_NOT_CONFIGURED_SHORT_TEXT = "❌ Eventbrite non è configurato."
SINGLE_VENUE_TEXT = "ℹ️ C'è una sola sede configurata. Aggiungi le altre con EVENTBRITE_VENUE_ID_ALTERNATIVES."
CHOOSE_VENUE_TEXT = "📍 Scegli la sede Eventbrite per i nuovi eventi:"
BOT_STATUS_PAUSED = "🔴 IN PAUSA (monitoraggio canale eventi disattivato)"
BOT_STATUS_ACTIVE = "🟢 ATTIVO (monitoraggio canale eventi funzionante)"
PUBLISH_MODE_EVENTBRITE_ONLY = "🎟️ SOLO EVENTBRITE (nessun pulsante Telegram, niente storia Instagram)"
PUBLISH_MODE_NORMAL = "📣 normale"


def format_bot_status(paused, eventbrite_only, venue=None):
    status = BOT_STATUS_PAUSED if paused else BOT_STATUS_ACTIVE
    mode = PUBLISH_MODE_EVENTBRITE_ONLY if eventbrite_only else PUBLISH_MODE_NORMAL
    text = f"Stato del bot: {status}\nModalità pubblicazione: {mode}"
    if venue:
        text += f"\nSede Eventbrite: {venue}"
    return text


# ---------------------------------------------------------------------------
# /event_publish_eventbrite
# ---------------------------------------------------------------------------
PUBLISH_EVENTBRITE_USAGE = "❌ Rispondi al messaggio di un evento (quello con i pulsanti) oppure usa: /event_publish_eventbrite <id>"
PUBLISH_EVENTBRITE_PENDING = "❌ Pubblica prima l'evento su Telegram (oppure usa 🚀 Publish + Eventbrite sulla scheda)"
PUBLISH_EVENTBRITE_CANCELLED = "❌ Evento annullato: riattivalo prima"


# ---------------------------------------------------------------------------
# /event_regenerate_story
# ---------------------------------------------------------------------------
REGENERATE_STORY_USAGE = ("❌ Rispondi al messaggio di un evento (quello con i pulsanti) per rigenerarne la storia,\n"
                          "oppure usa: /event_regenerate_story <id>")
REGENERATE_STORY_PROGRESS = "⏳ Rigenerazione Storia Instagram in corso..."
STORY_SEND_ERROR = "❌ Errore durante l'invio dell'immagine della storia."
STORY_GENERATION_ERROR = "❌ Errore durante la generazione dell'immagine della storia."


def format_story_regenerated_caption(event_id, title):
    return f"✅ Immagine Storia rigenerata per l'evento #{event_id} ({title or 'Senza Titolo'})."


# ---------------------------------------------------------------------------
# Admin preview warnings
# ---------------------------------------------------------------------------
def format_date_anomaly_warning(warnings):
    return "🚨 ATTENZIONE ANOMALIE DATA:\n" + "\n".join(warnings) + "\n👉 Usa /event_edit_date per correggere prima di approvare.\n\n"


def format_caption_limit_warning(length, limit):
    return (
        f"🚨 ATTENZIONE LIMITE CARATTERI:\n"
        f"⚠️ IL TESTO DELL'EVENTO SUPERA I {limit} CARATTERI ({length}/{limit})!\n"
        f"La pubblicazione sul canale fallirà. Riduci la descrizione con /event_edit_description prima di approvare.\n\n"
    )


# ---------------------------------------------------------------------------
# Reposts (/event_repost, /event_schedule*, daily digest)
# ---------------------------------------------------------------------------
REPOST_USAGE = (
    "Uso: <code>/event_repost DATE SEATS</code>\n"
    "Esempi:\n"
    "• <code>/event_repost oggi 4</code>\n"
    "• <code>/event_repost LUN 4</code>\n"
    "• <code>/event_repost MER 21:00 4</code>\n"
    "• <code>/event_repost 15-10-2026 21:00 4</code>"
)
REPOST_NO_REPLY = "❌ Rispondi al messaggio dell'evento che vuoi ripubblicare.\n" + REPOST_USAGE
REPOST_MISSING_PARAMS = "❌ Parametri mancanti.\n" + REPOST_USAGE
REPOST_INVALID_DATE = (
    "❌ Formato data non valido.\n"
    "Puoi usare: 'oggi', 'LUN', 'MER', 'VEN', oppure DD-MM-YYYY (con orario opzionale, es. 'MER 21:00' o '15-10-2026 21:00')."
)
NO_TEXT_IN_REPLIED_MESSAGE = "❌ Nessun testo trovato nel messaggio risposto."
REPOST_DONE = "✅ Evento ripubblicato ed elaborato! Conferma la pubblicazione con i pulsanti sopra."
SCHEDULE_INVOKE_USAGE = "❌ Specifica l'ID dell'evento programmato (es. /event_schedule_invoke 123)."
SCHEDULED_EVENT_NO_TEXT = "❌ L'evento programmato non contiene testo."
SCHEDULE_INVALID_DATE_FOR_EXISTING = "❌ Formato data non valido per la programmazione specifica."
SCHEDULE_DATE_UPDATED_PREFIX = "✅ Data specifica aggiornata!\n\n"
SCHEDULE_NO_REPLY = (
    "❌ Rispondi al messaggio dell'evento che vuoi programmare per il repost.\n"
    "Uso: <code>/event_schedule [DATA HH:MM]</code>\n"
    "Esempi:\n"
    "• <code>/event_schedule</code> (mostra i giorni di apertura)\n"
    "• <code>/event_schedule 09-10-2026 21:00</code>"
)
SCHEDULE_INVALID_DATE = "❌ Formato data specifica non valido. Usa DD-MM-YYYY [HH:MM] o oggi/LUN/MER/VEN."
SCHEDULE_SAVE_ERROR = "❌ Errore durante il salvataggio della programmazione nel database."
SCHEDULE_UPDATE_NO_REPLY = (
    "❌ Rispondi al messaggio dell'evento con cui vuoi aggiornare la programmazione.\n"
    "Uso: <code>/event_schedule_update SCHEDULED_ID</code> (es. <code>/event_schedule_update 1</code>)"
)
SCHEDULE_UPDATE_USAGE = "❌ Specifica l'ID dell'evento programmato da aggiornare (es. /event_schedule_update 1)."
SCHEDULE_UPDATE_ERROR = "❌ Errore durante l'aggiornamento nel database."
SCHEDULE_LIST_EMPTY = "📋 Nessun evento programmato per il repost nel database."


def format_scheduled_event_not_found(sched_id):
    return f"❌ Evento programmato #{sched_id} non trovato."


def format_scheduled_event_invoked(sched_id):
    return f"✅ Evento programmato #{sched_id} invocato e pronto per la revisione!"


def format_scheduled_event_updated(sched_id):
    return f"✅ Evento programmato #{sched_id} aggiornato con successo con il nuovo contenuto!"


def format_schedule_list_header(count):
    return f"📋 <b>Eventi programmati per il reposting ({count}):</b>\n"


def format_schedule_list_entry(sched_event):
    sched_id = sched_event['id']
    days = sched_event.get('schedule_days') or []
    return (
        f"• <b>{html.escape(sched_event.get('title') or 'Evento')}</b> (ID #{sched_id})\n"
        f"  🗓️ Giorni: {', '.join(days) if days else 'Nessuno'} | Data: {sched_event.get('specific_date') or 'Nessuna'}\n"
        f"  👉 Invia per preparare il post: <code>/event_schedule_invoke {sched_id}</code>\n"
        f"  ⚙️ Gestisci programmazione: <code>/event_schedule {sched_id}</code>\n"
    )


def format_reposts_digest_header(weekday_it, today_str):
    return f"📅 <b>Eventi programmati per il reposting di oggi ({weekday_it} {today_str}):</b>\n"


def format_reposts_digest_entry(sched_event):
    sched_id = sched_event['id']
    return (
        f"• <b>{html.escape(sched_event.get('title') or 'Evento')}</b> (ID #{sched_id})\n"
        f"  👉 Invia per preparare il post: <code>/event_schedule_invoke {sched_id}</code>\n"
    )
