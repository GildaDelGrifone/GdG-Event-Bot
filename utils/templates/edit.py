"""/event_edit_* command replies."""

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
