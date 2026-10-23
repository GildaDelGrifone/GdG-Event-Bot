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


APPROVED_SUFFIX = "\n\n✅ APPROVATO"


CANCELLED_SUFFIX = "\n\n⚠️ ANNULLATO"


REACTIVATED_SUFFIX = "\n\n✅ RIATTIVATO"


DISCARDED_SUFFIX = "\n\n❌ SCARTATO"


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
        f"Se la didascalia supera i {CAPTION_LIMIT} caratteri, riduci la descrizione con /event_edit_description e riprova ad approvare."
    )


def format_approved_without_telegram(event_id):
    return f"🔇 Evento #{event_id} approvato senza pubblicazione su Telegram."
