"""Telegram command menu: (command, description) pairs registered at startup."""

DEFAULT_COMMAND_DESCRIPTIONS = (
    ("start", "Avvia il bot e visualizza info o iscritti"),
    ("event_mine", "Mostra gli eventi a cui sei prenotato"),
    ("event_next", "[gg-mm-aaaa|oggi|lunedì…] Mostra gli eventi in programma, o solo quelli di un giorno"),
    ("event_subs", "<id> Mostra gli iscritti di un evento"),
)


ADMIN_COMMAND_DESCRIPTIONS = (
    ("event_process", "<testo o foto> Analizza e crea bozza evento"),
    ("ep", "<testo o foto> Analizza e crea bozza evento"),
    ("event_generate", "<istruzioni> Genera evento e locandina con AI"),
    ("recap_generate", "[DD-MM-YYYY] Genera recap giornaliero (/rg)"),
    ("rg", "[DD-MM-YYYY] Genera recap giornaliero"),
    ("recap_article", "[DD-MM-YYYY] Rigenera solo l'articolo della serata"),
    ("bot_pause", "Mette in pausa l'intercettazione automatica"),
    ("bot_resume", "Riattiva l'intercettazione automatica"),
    ("bot_status", "Mostra lo stato operativo del bot"),
    ("bot_eventbrite_venue", "Scegli la sede Eventbrite per i nuovi eventi"),
    ("bot_eventbrite_only_toggle", "Attiva/disattiva la modalità solo Eventbrite"),
    ("event_edit_title", "<Titolo> Modifica il titolo dell'evento"),
    ("event_edit_date", "<DD-MM-YYYY HH:MM> Modifica data e ora"),
    ("event_edit_system", "<Sistema> Modifica il sistema/gioco"),
    ("event_edit_host", "<Nome> Modifica Master o Host"),
    ("event_edit_type", "<rpg|boardgame> Imposta tipo tavolo"),
    ("event_edit_seats", "<X/Y> Modifica posti disponibili/totali"),
    ("event_edit_booked", "<N> Modifica posti già prenotati"),
    ("event_edit_extra", "<Note> Modifica dettagli/note extra"),
    ("event_edit_extra_add", "<Note> Aggiunge dettagli/note extra"),
    ("event_edit_description", "<Testo> Modifica la descrizione"),
    ("event_edit_image", "[ID] Allega nuova foto per la locandina"),
    ("event_regenerate_story", "[ID] Rigenera immagine Storia Instagram"),
    ("event_publish_eventbrite", "[ID] Pubblica l'evento su Eventbrite"),
    ("event_sub_add", "<ID> @username [posti] Aggiunge iscritto"),
    ("event_sub_remove", "<ID> @username [posti] Rimuove iscritto"),
    ("event_repost", "<DATE> <SEATS> Ripubblica evento con nuova data e posti"),
    ("event_schedule", "[ID] [DATA HH:MM] Programma ripubblicazione evento"),
    ("event_schedule_invoke", "<ID> Prepara il post dell'evento programmato"),
    ("event_schedule_update", "<ID> Aggiorna il contenuto dell'evento programmato"),
    ("event_schedule_list", "Mostra tutti gli eventi programmati per il repost"),
)
