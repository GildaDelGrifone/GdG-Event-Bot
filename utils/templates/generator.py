"""/event_generate texts."""

GENERATE_USAGE = (
    "ℹ️ **Uso del comando /event_generate:**\n"
    "Invia il comando seguito dai dettagli dell'evento, oppure rispondi a un messaggio.\n\n"
    "**Esempi:**\n"
    "`/event_generate Catan e Carcassonne, venerdì 10 ottobre ore 21, Host Destard, 4 posti`\n"
)


GENERATE_PROGRESS = "⏳ Generazione evento in corso con AI e BoardGameGeek..."


GENERATE_QUOTA_DEPLETED = "Crediti Gemini AI esauriti. Impossibile generare l'evento."


GENERATE_PARSE_FAILED = "Impossibile interpretare l'evento con l'AI. Verifica il messaggio fornito."


GENERATE_SAVE_ERROR = "Errore durante il salvataggio dell'evento nel database."


GENERATE_SUCCESS = "Evento generato con successo e inviato in revisione."


def format_generate_result(success, result_text):
    return f"{'✅' if success else '❌'} {result_text}"
