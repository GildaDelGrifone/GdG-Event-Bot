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


# ---------------------------------------------------------------------------
# Admin card status suffixes (appended to the review card, stripped when the status changes)
# ---------------------------------------------------------------------------
APPROVED_SUFFIX = "\n\n✅ APPROVATO"
CANCELLED_SUFFIX = "\n\n⚠️ ANNULLATO"
REACTIVATED_SUFFIX = "\n\n✅ RIATTIVATO"
DISCARDED_SUFFIX = "\n\n❌ SCARTATO"


# ---------------------------------------------------------------------------
# /event_edit_* commands
# ---------------------------------------------------------------------------
EDIT_EVENTBRITE_SEATS_BLOCKED = ("❌ Impossibile: {seats} posti risultano prenotati su Eventbrite e non possono essere rimossi da qui. "
                                 "Gestiscili dalla dashboard Eventbrite.")
EDIT_IMAGE_MISSING = "Devi allegare un'immagine (o un album) a questo comando, oppure rispondere a un'immagine con il comando."
EDIT_IMAGE_SAVE_ERROR = "Errore durante il salvataggio dell'immagine."
EDIT_DATE_INVALID = (
    "❌ Formato data non valido.\n"
    "Usa il formato DD-MM-YYYY o DD-MM-YYYY HH:MM (es. 05-09-2026 oppure 05-09-2026 21:00) (i / funzionano anche)."
)
EDIT_SEATS_INVALID = "Formato non valido. Usa 'X/Y' (es. '2/2'), un numero intero (es. '4'), o 'null'."
EDIT_BOOKED_INVALID = "Il valore per i posti prenotati deve essere un numero intero."
EDIT_EXTRA_ADD_USAGE = "Devi specificare il testo da aggiungere. (es. <code>/event_edit_extra_add Note aggiuntive</code>)"
EDIT_TYPE_INVALID = (
    "❌ Tipo non valido.\n"
    "Usa <code>/event_edit_type rpg</code> (o gdr) per gioco di ruolo (Master),\n"
    "oppure <code>/event_edit_type boardgame</code> (o tavolo) per altri giochi (Host)."
)
EDIT_NO_REPLY = "Rispondi al messaggio dell'evento che vuoi modificare."
EDIT_EVENT_ID_UNKNOWN = ("Impossibile determinare l'ID dell'evento da questo messaggio. "
                         "Assicurati di rispondere al messaggio con i pulsanti (Publish, Discard, Cancel).")
EDIT_EVENT_NOT_FOUND = "Evento non trovato nel database (potrebbe essere stato eliminato o scartato)."
EDIT_DB_ERROR = "Errore durante l'aggiornamento del database."
EDIT_EVENT_MISSING_AFTER_UPDATE = "Evento non trovato nel DB dopo l'aggiornamento."


def format_edit_eventbrite_seats_blocked(seats):
    return EDIT_EVENTBRITE_SEATS_BLOCKED.format(seats=seats)


def format_caption_overflow_warning(length, limit):
    return (
        f"⚠️ <b>Attenzione:</b> il testo dell'evento supera la dimensione massima per la didascalia "
        f"({length}/{limit} caratteri)!\n"
        f"Se l'evento ha un'immagine, la pubblicazione o l'aggiornamento della didascalia fallirà."
    )


def format_edit_done(field):
    return f"✅ Campo '{field}' aggiornato con successo!"


# ---------------------------------------------------------------------------
# Approval / cancellation callbacks (bot/callbacks/events.py)
# ---------------------------------------------------------------------------
POPUP_NOTHING_TO_CANCEL_ON_EVENTBRITE = "Niente da annullare su Eventbrite per questo evento."
POPUP_LOADING_LOGO = "Carico il logo…"
POPUP_CANCELLATION_ABORTED = "Annullamento interrotto."
POPUP_ALREADY_CANCELLED = "Evento già annullato."
POPUP_REACTIVATED = "Evento riattivato!"
STORY_GENERATION_PROGRESS = "⏳ Generazione e pubblicazione Storia Instagram in corso..."
STORY_GENERATED_CAPTION = "✅ Immagine Storia generata (Pubblicazione IG disabilitata temporaneamente per test)."


def format_channel_publish_error(event_id, error):
    return (
        f"❌ Errore pubblicazione evento #{event_id} sul canale: {error}\n"
        "Se la didascalia supera i 1024 caratteri, riduci la descrizione con /event_edit_description e riprova ad approvare."
    )


def format_approved_without_telegram(event_id):
    return f"🔇 Evento #{event_id} approvato senza pubblicazione su Telegram."


# ---------------------------------------------------------------------------
# /event_process, /event_next, /event_subs, /start
# ---------------------------------------------------------------------------
PROCESS_NO_TEXT_IN_REPLY = "Nessun testo trovato nel messaggio o nel comando. Includi il testo o invia una didascalia."
PROCESS_NO_TEXT = "Rispondi a un messaggio o fornisci il testo."
PROCESSED_REPLY = "Processato il messaggio risposto."
PROCESSED_TEXT = "Processato il testo inviato."
EVENT_NEXT_INVALID_DATE = "❌ Data non valida. Usa /event_next [gg-mm-aaaa | oggi | lunedì | mercoledì | venerdì | sabato | domenica]"
EVENT_NEXT_DATE_PAST = "ℹ️ Quella data è già passata."
EVENT_NEXT_NONE = "Nessun evento in programma per oggi o per i prossimi giorni."
EVENT_NEXT_PENDING_SUFFIX = " <i>[In attesa di approvazione]</i>"
EVENT_NEXT_CANCELLED_SUFFIX = " ❌ <i>[ANNULLATO]</i>"
EVENT_NEXT_TITLE_DEFAULT = "Eventi di oggi e prossimi in programma"
EVENT_NEXT_HINT = "<i>Per visualizzare i partecipanti usa /event_subs &lt;id&gt; oppure clicca su 👥 Iscritti.</i>"
EVENT_SUBS_USAGE = "❌ Specifica l'ID dell'evento (es. /event_subs 123 o /subs 123)."
EVENT_SUBS_INVALID_ID = "❌ ID evento non valido. Deve essere un numero intero."
EVENT_REMOVED = "❌ Evento non trovato o già rimosso."
START_INVALID_ID = "❌ ID evento non valido."
START_WELCOME = (
    "👋 Ciao! Sono il bot per la gestione degli eventi della Gilda del Grifone.\n\n"
    "Puoi visualizzare le proposte e gestire le prenotazioni direttamente dai pulsanti interattivi sul canale e nel gruppo di discussione!\n\n"
    "Inoltre puoi visualizzare facilmente gli eventi in programma e i partecipanti con i seguenti comandi:\n"
    "/event_next [data] - Visualizza gli eventi in programma, o solo quelli di un giorno (gg-mm-aaaa, oggi, lunedì, mercoledì, venerdì, sabato, domenica)\n"
    "/event_subs <id> - Visualizza i partecipanti a un evento specifico\n"
)


def format_event_next_none_for_day(day_label):
    return f"Nessun evento in programma per {day_label}."


def format_event_next_prefix(day_label=""):
    title = f"Eventi di {day_label}" if day_label else EVENT_NEXT_TITLE_DEFAULT
    return f"📅 <b>{title}:</b>\n{EVENT_NEXT_HINT}\n\n"


def format_event_next_entry(event_id, escaped_title, status_suffix, escaped_date, links):
    return (
        f"• <b>{escaped_title}</b> (ID {event_id}){status_suffix}\n"
        f"  🗓️ Data: {escaped_date}\n"
        f"  🔗 {' | '.join(links)}\n"
    )


# ---------------------------------------------------------------------------
# /recap_generate
# ---------------------------------------------------------------------------
RECAP_INVALID_DATE = "❌ Formato data non valido.\nUsa il formato DD-MM-YYYY (es. /recap_generate 05-09-2026)."


def format_recap_done(date_str):
    return f"Recap generato per la data: {date_str or 'Oggi'}"


# ---------------------------------------------------------------------------
# Subscribers (/event_sub_add, /event_sub_remove, management panel)
# ---------------------------------------------------------------------------
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


def format_admin_failure(message):
    return f"❌ {message}"


def format_admin_success(message):
    return f"✅ {message}"


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


# ---------------------------------------------------------------------------
# Booking, status notices, recap/WordPress and schedule/venue callbacks
# ---------------------------------------------------------------------------
POPUP_TABLE_FULL = "I posti per questo tavolo sono esauriti!"
POPUP_SCHEDULE_NOT_FOUND = "Evento programmato non trovato."
POPUP_SCHEDULE_DELETED = "Programmazione eliminata."
SCHEDULE_DELETED_TEXT = "🗑️ Programmazione reposting eliminata."
POPUP_VENUE_GONE = "Sede non più configurata."
POPUP_VENUE_UPDATED = "Sede aggiornata"
RECAP_PUBLISHED_SUFFIX = "\n\n✅ RECAP PUBLISHED"
RECAP_DISCARDED_SUFFIX = "\n\n❌ RECAP SCARTATO"
ARTICLE_PUBLISHED_SUFFIX = "\n\n✅ ARTICOLO PUBBLICATO PUBBLICAMENTE!"
ARTICLE_PUBLISH_ERROR_SUFFIX = "\n\n❌ Errore durante la pubblicazione dell'articolo."
WORDPRESS_CREATE_ERROR = "❌ Errore durante la creazione dell'articolo su WordPress."
WORDPRESS_DRAFT_PROGRESS = "⏳ Generazione della bozza su WordPress in corso..."
RECAP_STORY_CAPTION = "✅ Immagine Storia RECAP generata (Pubblicazione IG disabilitata temporaneamente per test)."
RECAP_STORY_ERROR = "❌ Errore durante la generazione della Storia Recap."


def format_status_notice(icon, status_word, event_link, subscribers_label=None, tags=None):
    text = f"{icon} <b>ATTENZIONE:</b> L'evento {event_link} è stato <b>{status_word}</b>!"
    if tags:
        text += f"\n\n{subscribers_label}: {tags}"
    return text


def format_wordpress_draft_created(wp_link):
    return f"✅ Bozza articolo creata su WordPress:\n{wp_link}\n\nClicca qui sotto per pubblicarla pubblicamente."


def format_schedule_day_toggled(day, active):
    return f"{'Attivato' if active else 'Disattivato'}: {day}"


def format_venue_selected(venue):
    return f"📍 Sede Eventbrite per i nuovi eventi: {venue}"


# ---------------------------------------------------------------------------
# Eventbrite admin messages and buttons (bot/service/eventbrite.py)
# ---------------------------------------------------------------------------
NOT_CONFIGURED = "❌ Eventbrite non configurato"
DATE_NOT_UPDATED = "⚠️ Evento #{id}: data non aggiornata su Eventbrite ({reason})."
EVENTBRITE_MUST_BE_APPROVED = "❌ Eventbrite: l'evento deve essere pubblicato su Telegram (stato: approvato)."
EVENTBRITE_CANCELLED_CANNOT_REACTIVATE = "ℹ️ L'evento era stato annullato su Eventbrite e non può essere riattivato."
EVENTBRITE_SOLD_OUT_NOTE = "\nℹ️ Evento esaurito: pubblicato senza biglietti acquistabili (si riaprono se si libera un posto)."
EVENTBRITE_REPUBLISH_HINT = " Puoi ripubblicarlo con [🎟️ Pubblica su Eventbrite]."
EVENTBRITE_STILL_TELEGRAM_ACTIVE = " L'evento resta attivo su Telegram."
EVENTBRITE_ORDERS_STILL_ACTIVE_PREFIX = "ℹ️ Restano ancora ordini attivi.\n"

BUTTON_EB_RETRY_LOGO = "🖼️ Riprova caricamento logo"
BUTTON_EB_RECREATE = "🎟️ Ricrea su Eventbrite"
BUTTON_EB_DASHBOARD = "🎟️ Apri dashboard Eventbrite"
BUTTON_EB_CANCEL_DONE = "🔁 Ho annullato tutto, completa"


def format_eb_collection_warning(event_id, reason):
    return f"⚠️ Evento #{event_id} non aggiunto alla collezione Eventbrite ({reason})"


def format_eb_link_removed(event_id, can_republish):
    text = f"ℹ️ Evento #{event_id} eliminato su Eventbrite: collegamento rimosso."
    return text + EVENTBRITE_REPUBLISH_HINT if can_republish else text


def format_eb_error(error):
    return f"❌ Eventbrite: {error}"


def format_eb_already_published(url):
    return f"ℹ️ Evento già pubblicato su Eventbrite: {url}"


def format_eb_publish_failed(event_id, error):
    return (
        f"❌ Eventbrite: pubblicazione fallita per #{event_id} ({error}). "
        "Riprova con [🎟️ Pubblica su Eventbrite]: riprenderà dal punto in cui si è interrotta."
    )


def format_eb_logo_not_uploaded(reason):
    return f"⚠️ Logo non caricato su Eventbrite ({reason})"


def format_eb_logo_not_updated(event_id, reason):
    return f"⚠️ Logo non aggiornato su Eventbrite per #{event_id} ({reason})"


def format_eb_published(url, sold_out=False, venue=None):
    text = f"✅ Evento pubblicato su Eventbrite: {url}"
    if sold_out:
        text += EVENTBRITE_SOLD_OUT_NOTE
    if venue:
        text += f"\n📍 Sede: {venue}"
    return text


def format_eb_sync_failed(event_id, error):
    return f"⚠️ Sync Eventbrite fallita per #{event_id}: {error}"


def format_eb_not_active(event_id):
    return f"❌ Evento #{event_id} non è attivo su Eventbrite"


def format_eb_no_image(event_id):
    return f"❌ Evento #{event_id}: nessuna immagine da caricare. Aggiungila con /event_edit_image"


def format_eb_logo_uploaded(event_id):
    return f"✅ Logo caricato su Eventbrite per l'evento #{event_id}"


def format_eb_order_button(name, seats):
    return f"❌ {name} ({seats})"


def format_eb_orders_to_cancel(event_id, count, hidden=0):
    text = (
        f"⚠️ Evento #{event_id}: {count} prenotazioni Eventbrite da annullare dalla dashboard "
        "(Eventbrite avvisa i partecipanti via email). Apri ogni ordine e premi \"Cancel order\"; "
        "quando hai finito il bot completa l'annullamento."
    )
    if hidden > 0:
        text += f" (… altri {hidden} ordini nella dashboard)"
    return text


def format_eb_cancel_failed(event_id, error):
    return f"⚠️ Annullamento su Eventbrite fallito per #{event_id}: {error}"


def format_eb_taken_offline(event_id):
    return f"✅ Evento #{event_id} messo offline su Eventbrite (nessuna prenotazione)."


def format_eb_cancelled_too(event_id):
    return f"✅ Evento #{event_id} annullato anche su Eventbrite"


def format_eb_already_cancelled(event_id):
    return f"✅ Evento #{event_id} già annullato su Eventbrite"


def format_eb_cancel_incomplete(event_id, error):
    return f"⚠️ Annullamento su Eventbrite non completato per #{event_id}: {error}"


def format_eb_all_orders_cancelled(event_id):
    return f"✅ Tutte le prenotazioni annullate: evento #{event_id} annullato anche su Eventbrite"


def format_eb_cannot_cancel_yet(event_id, url):
    return f"⚠️ Eventbrite non permette ancora di annullare l'evento #{event_id}. Annullalo dalla dashboard: {url}"


def format_eb_cancelled_keep_telegram(event_id):
    return f"✅ Evento #{event_id} annullato su Eventbrite (resta attivo su Telegram)"


def format_eb_reactivate_failed(event_id, error):
    return f"⚠️ Riattivazione su Eventbrite fallita per #{event_id}: {error}"


def format_eb_reactivated(event_id):
    return f"✅ Evento #{event_id} riattivato anche su Eventbrite"


def format_eb_publish_in_progress(event_id):
    return f"⏳ Pubblicazione su Eventbrite già in corso per #{event_id}"


# ---------------------------------------------------------------------------
# Booking notices, admin action notices, Eventbrite poller and nightly cleanup
# ---------------------------------------------------------------------------
EVENTBRITE_TAKEN = "😕 L'ultimo posto è appena stato prenotato su Eventbrite: la tua prenotazione non è stata registrata."
CONFLICT_WARNING_FOOTER = (
    "\n\n<i>La tua prenotazione è stata registrata regolarmente. "
    "Se necessario, ricordati di liberare il posto dall'evento a cui non parteciperai!</i>"
)


def format_seats_count(count):
    return f"{count} posto" if count == 1 else f"{count} posti"


def format_conflict_warning(user_tag, count, items):
    if count == 1:
        header = f"⚠️ <b>Attenzione {user_tag}:</b> risulti già iscritto a un altro evento per la stessa data:\n"
    else:
        header = f"⚠️ <b>Attenzione {user_tag}:</b> risulti già iscritto ad altri {count} eventi per la stessa data:\n"
    return header + "\n".join(items) + CONFLICT_WARNING_FOOTER


def format_conflict_item(event_link, system=None):
    system_str = f" (<i>{html.escape(system)}</i>)" if system else ""
    return f"• {event_link}{system_str}"


def format_booking_notice(user_mention, event_link):
    return f"✅ {user_mention} ha prenotato 1 posto per: {event_link}"


def format_unbooking_notice(user_mention, event_link):
    return f"❌ {user_mention} ha liberato 1 posto per: {event_link}"


def format_admin_action_notice(admin_suffix, icon, verb, user_tag, event_link):
    return (
        f"🛠️ <b>Operazione effettuata da un admin degli eventi{admin_suffix}:</b>\n"
        f"{icon} {verb} per {user_tag} per: {event_link}"
    )


def format_seats_added_verb(seats):
    return "Aggiunto 1 posto" if seats == 1 else f"Aggiunti {seats} posti"


def format_seats_removed_verb(seats):
    return "Rimosso 1 posto" if seats == 1 else f"Rimossi {seats} posti"


def format_eb_poll_event_cancelled(event_id, telegram_cancelled):
    if telegram_cancelled:
        return f"✅ Evento #{event_id} annullato su Eventbrite (iscritti avvisati da Eventbrite)"
    return f"⚠️ Evento #{event_id} annullato su Eventbrite ma attivo su Telegram"


def format_eb_poll_booked(name, seats_label, event_link):
    return f"🎟️ {html.escape(name)} ha prenotato {seats_label} tramite Eventbrite per: {event_link}"


def format_eb_poll_released(name, seats_label, event_link):
    return f"❌ {html.escape(name)} ha liberato {seats_label} (Eventbrite) per: {event_link}"


def format_eb_overbooking(event_id, booked, max_seats, last_telegram_user=None):
    who = f" Ultima prenotazione Telegram: {last_telegram_user}." if last_telegram_user else ""
    return (
        f"⚠️ Overbooking su #{event_id}: {booked}/{max_seats} "
        f"(prenotazione Eventbrite arrivata in contemporanea).{who}"
    )


def format_cleanup_label(event_id, title):
    return f"#{event_id} {title or 'Senza titolo'}"


def format_cleanup_pending_orders(label):
    return f"{label} (ordini ancora da annullare)"


def format_cleanup_refused(label, reason):
    return f"{label} (Eventbrite ha rifiutato: {reason})"


def format_cleanup_failed(label, error):
    return f"{label} (errore: {error})"


def format_cleanup_deleted(count, labels):
    return f"🧹 Eliminati da Eventbrite {count} eventi annullati: {', '.join(labels)}"


def format_cleanup_kept(labels):
    return f"⚠️ Non eliminati da Eventbrite: {', '.join(labels)}"


# ---------------------------------------------------------------------------
# Inline keyboard labels (bot/keyboards.py)
# ---------------------------------------------------------------------------
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


def format_decrement_seat_button(label, seats):
    return f"➖ {label} ({seats})"


def format_increment_seat_button(label, seats):
    return f"➕ {label} ({seats})"


def format_eventbrite_order_row_button(name, seats):
    return f"{EVENTBRITE_ROW_PREFIX}{name} ({seats})"
