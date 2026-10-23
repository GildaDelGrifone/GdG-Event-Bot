"""Bot control commands (pause/resume/status), Eventbrite-only mode and the venue picker."""

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


POPUP_VENUE_GONE = "Sede non più configurata."


POPUP_VENUE_UPDATED = "Sede aggiornata"


def format_venue_selected(venue):
    return f"📍 Sede Eventbrite per i nuovi eventi: {venue}"
