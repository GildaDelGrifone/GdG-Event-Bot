# Guida Rapida all'Uso - Gilda del Grifone Event Bot 🎲

Questa guida illustra le funzionalità principali del Bot e spiega come utilizzarlo per gestire gli eventi della Gilda del Grifone, dalle proposte di tavoli fino alle prenotazioni e ai recap giornalieri.

---

## 🌟 Funzionalità Principali

- **Creazione Eventi Intelligente:** Il bot legge i messaggi testuali (anche con locandine allegate) e struttura automaticamente i dati dell'evento grazie all'IA.
- **Generazione Automatica Eventi:** Creazione rapida di eventi da istruzioni libere con `/event_generate`, con recupero automatico delle scatole dei giochi da BoardGameGeek e composizione di collage per più giochi.
- **Prenotazioni Live (Inline):** Gli utenti possono prenotare o disdire il proprio posto direttamente dai pulsanti interattivi sotto i messaggi del canale Telegram.
- **Prevenzione Conflitti:** Il bot avvisa automaticamente gli utenti se si prenotano a più di un evento nello stesso giorno.
- **Recap Giornalieri:** Generazione automatica di collage di immagini e riepiloghi testuali per Telegram, con integrazione diretta verso le storie di Instagram e bozze per gli articoli di WordPress.

---

## 🛠️ Per gli Amministratori: Gestione degli Eventi

Gli amministratori gestiscono il bot tramite il **Gruppo Admin**.

### 1. Creare un Evento
- **Modalità Automatica:** Invia o inoltra semplicemente il messaggio di proposta (testo ed eventuale immagine) all'interno del Gruppo Admin. Il bot lo leggerà e genererà una scheda di anteprima (Draft).
- **Generazione con AI e BoardGameGeek (`/event_generate` o `/eg`):** Invia nel Gruppo Admin un messaggio con istruzioni libere (es. giochi, data, host, posti):
  `/event_generate Catan e Wingspan, venerdì 10 ottobre 21:00, host Destard, 4 posti` (oppure `/eg <testo>`)
  Il bot interpreterà la richiesta tramite l'IA, scaricherà le locandine ufficiali dei giochi da BoardGameGeek (componendo automaticamente un collage se sono presenti più giochi), genererà una sinossi rispettando il limite di 1024 caratteri della didascalia Telegram e sottoporrà la bozza a revisione admin.
- **Protezione del Canale Eventi Pubblico:** Se un utente o un amministratore invia *manualmente* una proposta di evento in modo diretto nel canale pubblico degli eventi, **il bot la cancellerà istantaneamente** per mantenere il canale pulito e standardizzato. Il messaggio originale verrà inoltrato automaticamente nel Gruppo Admin, dove potrà essere processato, revisionato dall'IA e infine pubblicato ufficialmente.
- **Modalità Manuale:** Se il bot è disabilitato o non ha catturato un messaggio, puoi forzare la lettura rispondendo al messaggio originale con il comando:
  `/event_process` (oppure `/ep`)

### 2. Modificare un Evento (Prima o Dopo la Pubblicazione)
Se l'IA ha commesso un errore o i dettagli del tavolo cambiano, puoi correggere i dati in tempo reale **rispondendo al messaggio dell'evento** (l'anteprima nel gruppo admin o il post già pubblicato) con uno di questi comandi:
- `/event_edit_title <Nuovo Titolo>`
- `/event_edit_date <DD-MM-YYYY HH:MM>` *(es. 05-09-2026 21:00 - calcolerà automaticamente il giorno della settimana)*
- `/event_edit_system <Sistema di Gioco>`
- `/event_edit_host <Nome del Master/Host>`
- `/event_edit_type <rpg|boardgame>` *(imposta se l'evento è un gioco di ruolo [Master] o gioco da tavolo [Host])*
- `/event_edit_seats <X/Y>` *(es. 0/5 per azzerare i posti occupati su 5 massimi)*
- `/event_edit_extra <Note extra, avvertenze o tag>`
- `/event_edit_description <Nuova descrizione dell'evento>`
- `/event_edit_image` *(allega una nuova foto o album in risposta alla scheda evento, o rispondi a una foto con `/event_edit_image <event_id>`)*
- `/event_regenerate_story` (o `/ers`) *(rigenera l'immagine della storia Instagram rispondendo alla scheda evento o specificando l'ID)*

### 3. Pubblicare o Annullare
Sotto l'anteprima dell'evento troverai i pulsanti:
- **[Publish Event]**: Approva l'evento e lo pubblica immediatamente sul canale pubblico.
- **[Discard Event]**: Scarta l'evento eliminandolo dal database.

Se un evento già pubblicato viene cancellato dal Master:
- Usa il pulsante **[❌ Annulla Evento]**. L'evento verrà segnato come `[ANNULLATO]` nel canale pubblico, i posti scenderanno a zero e verrà ignorato nei recap.

### 4. Gestione Manuale degli Iscritti
Se hai bisogno di forzare l'aggiunta o la rimozione di un utente (ad esempio se non hanno Telegram o hanno problemi tecnici):
1. Clicca su **[👥 Gestisci Iscritti]** sotto l'evento per vedere la lista completa dei giocatori e usare i pulsanti `➕` e `➖`.
2. Oppure usa i comandi (rispondendo al messaggio dell'evento o specificando l'ID):
   - `/event_sub_add @username [numero_posti]` *(es. `/event_sub_add @mario 2`)*
   - `/event_sub_remove @username [numero_posti]`

### 5. Generazione Recap
- **Automatica:** Il bot genera automaticamente un riepilogo giornaliero alle **16:00** nei giorni di apertura (Lunedì, Mercoledì, Venerdì, Sabato, Domenica).
- **Manuale:** Puoi forzare un recap in qualsiasi momento inviando il comando `/recap_generate` (o `/rg`). Per fare il recap di un giorno specifico usa `/rg DD-MM-YYYY`.
  *(Nota: se non ci sono eventi in programma per la data richiesta, il bot avvisa direttamente nel gruppo admin)*.
- Una volta generato il recap nel gruppo admin, puoi approvarlo cliccando **[Publish Recap]** per mandarlo sul canale, generare l'immagine per le storie di Instagram e redigere l'articolo WordPress.

### 6. Controlli Generali del Bot
- `/bot_pause`: Mette in pausa la lettura automatica dei messaggi per la creazione di eventi (utile durante lunghe discussioni nel canale).
- `/bot_resume`: Riattiva il bot.
- `/bot_status`: Mostra lo stato attuale del bot (Attivo/In pausa).
- `/event_next`: Mostra la lista di tutti gli eventi di oggi e futuri in ordine cronologico con data e link rapidi. Questo comando è **accessibile anche pubblicamente agli utenti** sia in chat privata col bot che nel gruppo discussione (disattivabile nel gruppo discussione tramite variabile d'ambiente `ALLOW_GROUP_EVENT_NEXT=false` per prevenire spam).

---

## 👤 Per gli Utenti: Prenotazione Posti e Consultazione Eventi

La prenotazione e la consultazione dei tavoli per i giocatori è semplicissima:
- **Per Consultare gli Eventi (`/event_next`):** Invia `/event_next` in chat privata col bot, clicca sul deep link diretto (`https://t.me/GdG_Event_bot?start=event_next`), oppure invialo nel gruppo discussione per visualizzare l'elenco cronologico di tutti gli eventi di oggi e futuri con i rispettivi link ai canali e alle discussioni.
- **Per Prenotarsi:** Clicca sul pulsante inline **[➕ Prenota]** (oppure **[🚫 Esauriti]** se non ci sono più posti disponibili). Il contatore dei posti si aggiornerà in tempo reale e il bot confermerà la prenotazione taggandoti nei commenti.
- **Per Vedere gli Iscritti:** 
  - Clicca sul pulsante **[👥 Lista]** sotto il messaggio dell'evento nel canale o nel gruppo discussione (il bot ti aprirà una chat privata mostrando l'elenco completo dei partecipanti senza intasare la chat di gruppo).
  - In alternativa, invia manualmente il comando `/event_subs <id>` (oppure `/subs <id>`, es. `/event_subs 42` o `/event_subs_42`).
  - Inoltre, l'elenco `/event_next` mostra i posti disponibili/totali per ciascun evento e include il deep link diretto `[👥 Iscritti]` per visualizzare immediatamente i partecipanti.
- **Per Disdire:** Clicca sul pulsante **[➖ Annulla]** per liberare il tuo posto e rimetterlo a disposizione di altri.
