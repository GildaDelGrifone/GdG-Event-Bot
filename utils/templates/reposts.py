"""Repost scheduling: /event_repost, /event_schedule*, the daily digest and schedule popups."""
import html
import re

from utils.date_utils import DAYS_IT as _DAYS_IT


def format_advance_days(days):
    if not days:
        return "lo stesso giorno"
    return f"{days} giorno prima" if days == 1 else f"{days} giorni prima"


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
        f"📌 <b>Data specifica impostata:</b> {spec_date}\n"
        f"⏳ <b>Promemoria:</b> {format_advance_days(scheduled_event.get('advance_days'))}\n\n"
        f"Tocca i pulsanti in basso per attivare/disattivare i giorni in cui ripubblicare l'evento "
        f"e per scegliere quanti giorni prima dell'evento ricevere il promemoria.\n\n"
        f"👉 Per programmare una data specifica (stessa sintassi di /event_edit_date) e, se vuoi, i giorni di anticipo N:\n"
        f"<code>/event_schedule {sched_id} [DD-MM-YYYY [HH:MM]] [N]</code>\n"
        f"(es. <code>/event_schedule {sched_id} 09-10-2026 21:00 2</code> oppure <code>/event_schedule {sched_id} 2</code>)"
    )


REPOST_UPDATE_REMINDER = (
    "💡 <i>Promemoria:</i> Puoi aggiornare il contenuto di un evento programmato rispondendo a un messaggio con il nuovo testo/locandina e usando:\n"
    "<code>/event_schedule_update ID</code>"
)


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
    "• <code>/event_schedule 09-10-2026 21:00</code>\n"
    "• <code>/event_schedule 09-10-2026 21:00 2</code> (promemoria 2 giorni prima)\n"
    "N (opzionale, 0-30) = giorni di anticipo del promemoria; 0 = lo stesso giorno."
)


SCHEDULE_INVALID_DATE = "❌ Formato data specifica non valido. Usa DD-MM-YYYY [HH:MM] o oggi/LUN/MER/VEN."


SCHEDULE_INVALID_ADVANCE = "❌ I giorni di anticipo devono essere un numero intero tra 0 e 30."


SCHEDULE_ADVANCE_UPDATED_PREFIX = "✅ Giorni di anticipo aggiornati!\n\n"


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
        f"  🗓️ Giorni: {', '.join(days) if days else 'Nessuno'} | Data: {sched_event.get('specific_date') or 'Nessuna'}"
        f" | Anticipo: {sched_event.get('advance_days') or 0} gg\n"
        f"  👉 Invia per preparare il post: <code>/event_schedule_invoke {sched_id}</code>\n"
        f"  ⚙️ Gestisci programmazione: <code>/event_schedule {sched_id}</code>\n"
    )


def format_reposts_digest_header(weekday_it, today_str):
    return f"📅 <b>Promemoria reposting di oggi ({weekday_it} {today_str}):</b>\n"


def format_reposts_digest_entry(sched_event, event_date):
    """event_date is the day of the event itself (today plus the template's advance_days)."""
    sched_id = sched_event['id']
    advance = sched_event.get('advance_days') or 0
    event_day = event_date.strftime("%d-%m-%Y")
    when = f"{_DAYS_IT[event_date.weekday()]} {event_day}" + (f" (tra {advance} giorni)" if advance > 1 else " (domani)" if advance == 1 else "")
    time_match = re.search(r'\b(\d{1,2}:\d{2})\b', sched_event.get('specific_date') or '')
    invoke_date = f"{event_day} {time_match.group(1)}" if time_match else event_day
    return (
        f"• <b>{html.escape(sched_event.get('title') or 'Evento')}</b> (ID #{sched_id})\n"
        f"  📆 Evento: {when}\n"
        f"  👉 Invia per preparare il post: <code>/event_schedule_invoke {sched_id} {invoke_date}</code>\n"
    )


POPUP_SCHEDULE_NOT_FOUND = "Evento programmato non trovato."


POPUP_SCHEDULE_DELETED = "Programmazione eliminata."


SCHEDULE_DELETED_TEXT = "🗑️ Programmazione reposting eliminata."


def format_schedule_day_toggled(day, active):
    return f"{'Attivato' if active else 'Disattivato'}: {day}"


def format_schedule_advance_popup(days):
    return f"Promemoria: {format_advance_days(days)}"
