"""/event_process, /event_next, /event_subs and /start texts."""

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


def format_event_next_subscribers_link(seats_str, bot_username=None, event_id=None):
    if bot_username:
        return f'<a href="https://t.me/{bot_username.lstrip("@")}?start=subs_{event_id}">👥 Iscritti</a> ({seats_str})'
    return f'👥 Iscritti ({seats_str})'
