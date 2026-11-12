"""Admin approval card: status suffixes, preview warnings, approval/cancellation popups and story captions."""
from utils.templates.common import CAPTION_LIMIT

REGENERATE_STORY_USAGE = ("❌ Rispondi al messaggio di un evento (quello con i pulsanti) per rigenerarne la storia,\n"
                          "oppure usa: /event_regenerate_story <id>")


REGENERATE_STORY_PROGRESS = "⏳ Rigenerazione Storia Instagram in corso..."


STORY_SEND_ERROR = "❌ Errore durante l'invio dell'immagine della storia."


STORY_GENERATION_ERROR = "❌ Errore durante la generazione dell'immagine della storia."


def format_story_regenerated_caption(event_id, title):
    return f"✅ Immagine Storia rigenerata per l'evento #{event_id} ({title or 'Senza Titolo'})."


def format_date_anomaly_warning(warnings):
    return "🚨 ATTENZIONE ANOMALIE DATA:\n" + "\n".join(warnings) + "\n👉 Usa /event_edit_date per correggere prima di approvare.\n\n"


def format_caption_limit_warning(length, limit):
    return (
        f"🚨 ATTENZIONE LIMITE CARATTERI:\n"
        f"⚠️ IL TESTO DELL'EVENTO SUPERA I {limit} CARATTERI ({length}/{limit})!\n"
        f"La pubblicazione sul canale fallirà. Riduci la descrizione con /event_edit_description prima di approvare.\n\n"
    )


PREVIEW_IMAGE_NOT_DELIVERED = "⚠️ Immagine non inviata (errore di rete con Telegram); verrà inviata alla pubblicazione.\n\n"


APPROVED_SUFFIX = "\n\n✅ APPROVATO"


def format_stale_card_popup(status):
    """Popup for Publish / Discard on a duplicate card of an event that is no longer pending."""
    if status == "cancelled":
        return "Questo evento è già stato annullato: usa ♻️ Riattiva Evento sulla card."
    if status == "discarded":
        return "Questo evento è stato scartato: usa ↩️ Ripristina sulla card."
    if status == "pending":
        return "Questo evento è già in attesa di approvazione."
    return "Questo evento è già pubblicato: per toglierlo usa ❌ Annulla Evento, non Scarta."


CANCELLED_SUFFIX = "\n\n⚠️ ANNULLATO"


REACTIVATED_SUFFIX = "\n\n✅ RIATTIVATO"


DISCARDED_SUFFIX = "\n\n❌ SCARTATO"


DELETED_SUFFIX = "\n\n🗑️ ELIMINATO"


POPUP_RESTORED = "Evento ripristinato: è di nuovo in attesa di approvazione."


POPUP_RESTORE_GONE = "Evento eliminato definitivamente: non si può più ripristinare."


POPUP_RESTORED_WITHOUT_IMAGE = "Evento ripristinato, ma la sua immagine non è più sul disco: caricala con /event_edit_image."


POPUP_NOTHING_TO_CANCEL_ON_EVENTBRITE = "Niente da annullare su Eventbrite per questo evento."


POPUP_LOADING_LOGO = "Carico il logo…"


POPUP_CANCELLATION_ABORTED = "Annullamento interrotto."


POPUP_ALREADY_CANCELLED = "Evento già annullato."


POPUP_REACTIVATED = "Evento riattivato!"


POPUP_DELETION_ABORTED = "Eliminazione interrotta."


POPUP_ALREADY_DELETED = "Questo evento è già stato eliminato."


POPUP_DELETE_ONLY_CANCELLED = "Si possono eliminare solo gli eventi annullati: annulla prima l'evento."


POPUP_DELETE_EB_ORDERS_OPEN = (
    "L'evento ha ancora prenotazioni attive su Eventbrite: annullale dalla dashboard "
    "(🔁 Completa annullamento) e poi riprova a eliminarlo."
)


POPUP_DELETE_EB_BUSY = "Pubblicazione su Eventbrite in corso: riprova tra qualche secondo."


def format_delete_eventbrite_failed(event_id, reason):
    return (
        f"⚠️ Evento #{event_id} non eliminato: Eventbrite ha rifiutato la cancellazione ({reason}).\n"
        "Non è stato toccato niente: risolvi su Eventbrite e riprova."
    )


def format_event_deleted_report(event_id, leftovers):
    """leftovers: (description, link or None) of the public messages the bot could not delete."""
    lines = [f"🗑️ Evento #{event_id} eliminato, ma questi messaggi non si sono potuti cancellare (fallo a mano):"]
    for description, link in leftovers:
        lines.append(f"- {description}: {link}" if link else f"- {description}")
    return "\n".join(lines)


def format_delete_db_failed(event_id):
    return f"❌ Evento #{event_id}: errore del database durante l'eliminazione, l'evento è ancora salvato. Controlla i log e riprova."


LEFTOVER_CHANNEL_POST = "post sul canale"


LEFTOVER_DISCUSSION_REPLY = "messaggio di prenotazione nel gruppo di discussione"


STORY_GENERATION_PROGRESS = "⏳ Generazione e pubblicazione Storia Instagram in corso..."


STORY_GENERATED_CAPTION = "✅ Immagine Storia generata (Pubblicazione IG disabilitata temporaneamente per test)."


def format_channel_publish_error(event_id, error):
    return (
        f"❌ Errore pubblicazione evento #{event_id} sul canale: {error}\n"
        f"Se la didascalia supera i {CAPTION_LIMIT} caratteri, riduci la descrizione con /event_edit_description e riprova ad approvare."
    )


def format_approved_without_telegram(event_id):
    return f"🔇 Evento #{event_id} approvato senza pubblicazione su Telegram."


# /event_cancel, /event_cancel_eventbrite, /event_delete: same confirmation as the card buttons, sent as a reply

EVENT_CANCEL_USAGE = "❌ Rispondi al messaggio di un evento (quello con i pulsanti) oppure usa: /event_cancel <id>"


EVENT_CANCEL_EVENTBRITE_USAGE = (
    "❌ Rispondi al messaggio di un evento (quello con i pulsanti) oppure usa: /event_cancel_eventbrite <id>"
)


EVENT_DELETE_USAGE = "❌ Rispondi al messaggio di un evento (quello con i pulsanti) oppure usa: /event_delete <id>"


CANCEL_ONLY_APPROVED = "❌ Si possono annullare solo gli eventi pubblicati."


def _event_label(event):
    return f"#{event['id']} «{event.get('title') or 'Senza titolo'}»"


def format_cancel_prompt(event):
    return (
        f"⚠️ Annullare l'evento {_event_label(event)}?\n"
        "Il post nel canale verrà segnato come annullato e gli iscritti avvisati nel gruppo."
    )


def format_eb_cancel_prompt(event):
    return f"⚠️ Annullare l'evento {_event_label(event)} solo su Eventbrite?\nSu Telegram resta attivo."


def format_delete_prompt(event):
    return (
        f"🗑️ Eliminare per sempre l'evento {_event_label(event)}?\n"
        "Spariscono post nel canale, messaggio di prenotazione nel gruppo, immagini e prenotazioni. Non si può annullare."
    )


def format_cancel_done(event_id):
    return f"⚠️ Evento #{event_id} annullato."


def format_eb_cancel_done(event_id):
    return f"🚫 Annullamento su Eventbrite dell'evento #{event_id} avviato."


def format_delete_done(event_id):
    return f"🗑️ Evento #{event_id} eliminato."
