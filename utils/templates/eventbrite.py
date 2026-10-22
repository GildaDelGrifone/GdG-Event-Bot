"""Eventbrite admin messages, poller notices and the nightly cleanup summary."""
import html


PUBLISH_EVENTBRITE_USAGE = "❌ Rispondi al messaggio di un evento (quello con i pulsanti) oppure usa: /event_publish_eventbrite <id>"


PUBLISH_EVENTBRITE_PENDING = "❌ Pubblica prima l'evento su Telegram (oppure usa 🚀 Publish + Eventbrite sulla scheda)"


PUBLISH_EVENTBRITE_CANCELLED = "❌ Evento annullato: riattivalo prima"


NOT_CONFIGURED = "❌ Eventbrite non configurato"


DATE_NOT_UPDATED = "⚠️ Evento #{id}: data non aggiornata su Eventbrite ({reason})."


EVENTBRITE_MUST_BE_APPROVED = "❌ Eventbrite: l'evento deve essere pubblicato su Telegram (stato: approvato)."


EVENTBRITE_CANCELLED_CANNOT_REACTIVATE = "ℹ️ L'evento era stato annullato su Eventbrite e non può essere riattivato."


EVENTBRITE_SOLD_OUT_NOTE = "\nℹ️ Evento esaurito: pubblicato senza biglietti acquistabili (si riaprono se si libera un posto)."


EVENTBRITE_REPUBLISH_HINT = " Puoi ripubblicarlo con [🎟️ Pubblica su Eventbrite]."


EVENTBRITE_STILL_TELEGRAM_ACTIVE = " L'evento resta attivo su Telegram."


EVENTBRITE_ORDERS_STILL_ACTIVE_PREFIX = "ℹ️ Restano ancora ordini attivi.\n"


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


EVENTBRITE_TAKEN = "😕 L'ultimo posto è appena stato prenotato su Eventbrite: la tua prenotazione non è stata registrata."


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
