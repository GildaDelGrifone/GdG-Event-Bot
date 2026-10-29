# Guida Rapida all'Uso - Gilda del Grifone Event Bot 🎲

Questa guida illustra le funzionalità principali del Bot e spiega come utilizzarlo per gestire gli eventi della Gilda del Grifone, dalle proposte di tavoli fino alle prenotazioni e ai recap giornalieri.

---

## 🌟 Funzionalità Principali

- **Creazione Eventi Intelligente:** Il bot legge i messaggi testuali (anche con locandine allegate) e struttura automaticamente i dati dell'evento grazie all'IA.
- **Generazione Automatica Eventi:** Creazione rapida di eventi da istruzioni libere con `/event_generate`, con recupero automatico delle scatole dei giochi (da BoardGameGeek anche senza token: l'ID del gioco viene da Wikidata o dall'IA ed è verificato sul nome BGG; in mancanza da Wikipedia e infine da una ricerca web verificata dall'IA; meglio nessuna immagine che una sbagliata) e composizione di collage per più giochi.
- **Prenotazioni Live (Inline):** Gli utenti possono prenotare o disdire il proprio posto direttamente dai pulsanti interattivi sotto i messaggi del canale Telegram.
- **Prevenzione Conflitti:** Il bot avvisa automaticamente gli utenti se si prenotano a più di un evento nello stesso giorno.
- **Prenotazioni anche su Eventbrite (opzionale):** Un evento può essere pubblicato anche su Eventbrite, così chi non usa Telegram può prenotare da lì. I posti sono unici: una prenotazione su una delle due piattaforme aggiorna subito la disponibilità dell'altra.
- **Recap Giornalieri:** Generazione automatica di collage di immagini e riepiloghi testuali per Telegram, con integrazione diretta verso le storie di Instagram e bozze per gli articoli del sito (Astro o WordPress).

---

## 🛠️ Per gli Amministratori: Gestione degli Eventi

Gli amministratori gestiscono il bot tramite il **Gruppo Admin**.

### 1. Creare un Evento
- **Modalità Automatica:** Invia o inoltra semplicemente il messaggio di proposta (testo ed eventuale immagine) all'interno del Gruppo Admin. Il bot lo leggerà e genererà una scheda di anteprima (Draft).
- **Generazione con AI e BoardGameGeek (`/event_generate`):** Invia nel Gruppo Admin un messaggio con istruzioni libere (es. giochi, data, host, posti):
  `/event_generate Catan e Wingspan, venerdì 10 ottobre 21:00, host Destard, 4 posti`
  Il bot interpreterà la richiesta tramite l'IA, scaricherà le locandine dei giochi (da BoardGameGeek se il bot ha il token `BGG_API_TOKEN`, altrimenti sempre da BoardGameGeek tramite l'ID trovato su Wikidata o proposto dall'IA e verificato, poi da Wikipedia o da una ricerca web in cui l'IA conferma che l'immagine è proprio quel gioco; componendo automaticamente un collage se sono presenti più giochi), genererà una sinossi rispettando il limite di 1024 caratteri della didascalia Telegram e sottoporrà la bozza a revisione admin.
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
- `/event_edit_extra_add <Nuovo testo extra da aggiungere su nuova riga>`
- `/event_edit_description <Nuova descrizione dell'evento>`
- `/event_edit_image` *(allega una nuova foto o album in risposta alla scheda evento, o rispondi a una foto con `/event_edit_image <event_id>`)*
- `/event_regenerate_story` *(rigenera l'immagine della storia Instagram rispondendo alla scheda evento o specificando l'ID)*

### 3. Pubblicare o Annullare
Sotto l'anteprima dell'evento troverai i pulsanti:
- **[Publish Event]**: Approva l'evento e lo pubblica immediatamente sul canale pubblico.
- **[Discard Event]**: Scarta l'evento eliminandolo dal database.

Se un evento già pubblicato viene cancellato dal Master:
- Usa il pulsante **[❌ Annulla Evento]**: il bot ti chiede conferma (**[✅ Sì, annulla]** oppure **[↩️ Indietro]**) e non cambia nulla finché non confermi. Dopo la conferma l'evento verrà segnato come `[ANNULLATO]` nel canale pubblico, i posti scenderanno a zero e verrà ignorato nei recap.

### 4. Pubblicare un Evento anche su Eventbrite
*(Disponibile solo se l'integrazione Eventbrite è configurata sul bot; altrimenti i pulsanti qui sotto non compaiono.)*
- **Subito, in fase di approvazione:** sull'anteprima usa **[🚀 Publish + Eventbrite]** al posto di *Publish*. L'evento viene pubblicato su Telegram e poi su Eventbrite; il bot risponde con il link Eventbrite.
- **Solo su Eventbrite:** attiva `/bot_eventbrite_only_toggle` (modalità solo Eventbrite). Le anteprime create da quel momento mostrano solo **[Discard]**, **[🚀 Telegram + EB]** e **[🎟️ Solo Eventbrite]**: niente *Publish*, e la storia Instagram non viene generata. **[🎟️ Solo Eventbrite]** approva l'evento ma **non** lo pubblica nel canale Telegram (niente post, niente messaggi nel gruppo discussione, nemmeno in caso di annullamento; le prenotazioni Eventbrite vengono invece annunciate nella chat admin, in risposta alla scheda dell'evento); **[🚀 Telegram + EB]** lo pubblica anche su Telegram. Rimanda il comando per tornare alle schede normali (si torna anche riavviando il bot, salvo `EVENTBRITE_ONLY_MODE=true`). Le schede già inviate non cambiano. Un evento solo Eventbrite non si può prenotare da Telegram.
- **Più tardi, su un evento già pubblicato:** usa il pulsante **[🎟️ Pubblica su Eventbrite]** sotto la scheda, oppure il comando `/event_publish_eventbrite` *(rispondendo alla scheda dell'evento, oppure `/event_publish_eventbrite <id>`)*. Fanno esattamente la stessa cosa. Una volta pubblicato, il pulsante diventa **[🎟️ Eventbrite]** e apre la dashboard dell'evento.
- **Cosa serve:** l'evento deve essere approvato, avere una data futura. Un evento `0/0 Completo` o già pieno viene pubblicato come esaurito: su Eventbrite si vede ma non si può prenotare, e le vendite si riaprono da sole se si libera un posto. Gli eventi senza limite di posti usano la capienza impostata sul bot (`EVENTBRITE_UNLIMITED_CAPACITY`). Se qualcosa si interrompe a metà, rilancia lo stesso pulsante: riprende dal punto in cui si era fermato.
- **Locandina:** il bot la carica come immagine dell'evento su Eventbrite, riprovando da solo in caso di blocchi temporanei. Se non ci riesce, l'evento viene comunque pubblicato e ricevi un avviso con il pulsante **[🖼️ Riprova caricamento logo]**: premilo per ritentare (oppure rimanda l'immagine con `/event_edit_image`).
- **Link:** il link Eventbrite compare solo nel messaggio di prenotazione del gruppo discussione (`🎟️ Prenota anche su Eventbrite`); il post del canale non cambia.
- **Posti esauriti su Eventbrite:** quando non resta nessun posto (da Telegram o da Eventbrite) le vendite su Eventbrite vengono chiuse ("Sold out" se c'è già qualche iscritto, altrimenti il biglietto viene nascosto); se si libera un posto le vendite si riaprono da sole.
- **Prenotazioni Eventbrite:** il bot controlla Eventbrite ogni pochi minuti. Le prenotazioni (e le disdette) arrivate da lì aggiornano i posti e vengono annunciate nel gruppo discussione (es. `🎟️ Mario R. ha prenotato 2 posti tramite Eventbrite`); compaiono col nome abbreviato, mai con l'email. Se il bot ha l'opzione `EVENTBRITE_BOOKING_NOTIFICATIONS=false`, i posti si aggiornano comunque ma l'annuncio non viene pubblicato.
- **Modifiche:** titolo, data, sistema, host, note, descrizione, tipo, posti e immagine modificati con i comandi `/event_edit_*` vengono riportati anche su Eventbrite. Non si può ridurre `/event_edit_booked` o `/event_edit_seats` sotto il numero di posti già prenotati su Eventbrite.
- **Annullare un evento:** con **[❌ Annulla Evento]** il bot annulla anche su Eventbrite.
  - *Nessuna prenotazione su Eventbrite:* l'evento viene messo offline; **[♻️ Riattiva Evento]** lo ripubblica.
  - *Con prenotazioni:* dopo la conferma le vendite vengono chiuse e l'evento rinominato `[ANNULLATO] …`. Eventbrite non permette al bot di annullare le prenotazioni, quindi ricevi **un pulsante per ogni ordine** (es. **[❌ Mario R. (2)]**): aprilo e premi *Cancel order* (Eventbrite avvisa il partecipante via email). Quando tutti gli ordini sono annullati il bot annulla l'evento su Eventbrite da solo entro pochi minuti, oppure subito con **[🔁 Ho annullato tutto, completa]** (se restano ordini attivi, ti rimanda i loro link; a evento annullato il messaggio con i link sparisce da solo).
  - Un evento annullato su Eventbrite non può essere riattivato: dopo **[♻️ Riattiva Evento]** il bot propone **[🎟️ Ricrea su Eventbrite]**.
- **Pulizia notturna di Eventbrite:** ogni sera alle **23:59** il bot elimina da Eventbrite gli eventi annullati di oggi (o di giorni passati, se il bot era spento), così dopo mezzanotte non compaiono più. Su Telegram non cambia nulla: eventi, prenotazioni, post nel canale e messaggi nel gruppo restano com'erano e nel gruppo non viene scritto niente. Sulla scheda di un evento ancora attivo su Telegram, il pulsante torna **[🎟️ Pubblica su Eventbrite]** se vuoi ripubblicarlo. Gli eventi con ordini ancora da annullare, o che Eventbrite non vuole eliminare, restano e ricevi un solo messaggio di riepilogo con l'elenco.
- **Annullare solo su Eventbrite:** sulla scheda di un evento pubblicato su Eventbrite, la seconda riga ha **[🎟️ Eventbrite]** e **[🚫 Annulla su Eventbrite]**. Dopo la conferma (**[✅ Sì, annulla su EB]** / **[↩️ Indietro]**) l'evento viene annullato solo su Eventbrite: su Telegram resta attivo e nel gruppo discussione non viene pubblicato nessun avviso (sparisce solo il link Eventbrite dal messaggio di prenotazione). Se ci sono prenotazioni Eventbrite ricevi i link per annullare ogni ordine; i posti liberati tornano prenotabili su Telegram. Finché restano ordini da annullare la riga mostra **[🔁 Completa annullamento]**, poi **[🎟️ Ricrea su Eventbrite]** per ripubblicarlo.

### 5. Ripubblicare un Evento (Repost e Programmazione)
Per riproporre un evento già fatto (stessa locandina e testo) con una nuova data:
- `/event_repost <DATA> <POSTI>`: rispondi al messaggio dell'evento da ripubblicare. La data può essere `gg-mm-aaaa [HH:MM]`, `oggi` o il prossimo `LUN`/`MER`/`VEN` (es. `/event_repost MER 21:00 4`, `/event_repost 15-10-2026 21:00 4`); i posti usano la stessa sintassi di `/event_edit_seats` (`X/Y`, un numero oppure `null` per posti illimitati). Il bot prepara la scheda di anteprima da approvare.
- **Programmare un repost ricorrente:** rispondi al messaggio dell'evento con `/event_schedule`. Si apre una scheda con i pulsanti dei giorni (`Lunedì`, `Mercoledì`, `Venerdì`, `Sabato`, `Domenica`, con ✅ attivo / ⬜ non attivo), **[🗑️ Elimina]** per cancellare la programmazione e **[❌ Chiudi]** per chiudere il messaggio. Per una data singola: `/event_schedule 09-10-2026 21:00`; per rivedere o cambiare una programmazione esistente: `/event_schedule <ID>` oppure `/event_schedule <ID> <data>`.
- **Ogni giorno alle 09:00** il bot manda nel gruppo admin l'elenco delle programmazioni di oggi, ognuna con il comando pronto `/event_schedule_invoke <ID>`: inviandolo, il bot crea la scheda di anteprima dell'evento con la data di oggi, pronta da approvare.
- `/event_schedule_list`: mostra tutte le programmazioni (ID, giorni attivi, data specifica).
- `/event_schedule_update <ID>`: rispondi a un nuovo post dell'evento per sostituire testo e locandina salvati in una programmazione.

### 6. Gestione Manuale degli Iscritti
Se hai bisogno di forzare l'aggiunta o la rimozione di un utente (ad esempio se non hanno Telegram o hanno problemi tecnici):
1. Clicca su **[👥 Gestisci Iscritti]** sotto l'evento per vedere la lista completa dei giocatori e usare i pulsanti `➕` e `➖`. Le prenotazioni Eventbrite sono segnate con `🎟️` e non hanno `➕`/`➖`: sono un unico pulsante che apre la pagina dell'ordine su Eventbrite, dove vanno gestite.
2. Oppure usa i comandi (rispondendo al messaggio dell'evento o specificando l'ID):
   - `/event_sub_add @username [numero_posti]` *(es. `/event_sub_add @mario 2`)*
   - `/event_sub_remove @username [numero_posti]`

### 7. Generazione Recap
- **Automatica:** Il bot genera automaticamente un riepilogo giornaliero alle **16:00** nei giorni di apertura (Lunedì, Mercoledì, Venerdì, Sabato, Domenica).
- **Manuale:** Puoi forzare un recap in qualsiasi momento inviando il comando `/recap_generate` (o `/rg`). Per fare il recap di un giorno specifico usa `/rg DD-MM-YYYY`.
- **Articolo:** sotto la bozza dell'articolo trovi **[Pubblica sul sito]** e **[🗑️ Scarta articolo]** (la bozza si scarta solo se non è già stata pubblicata). Per rigenerare solo l'articolo di una serata usa `/recap_article` (oggi) o `/recap_article DD-MM-YYYY`.
  *(Nota: se non ci sono eventi in programma per la data richiesta, il bot avvisa direttamente nel gruppo admin)*.
- Una volta generato il recap nel gruppo admin, puoi approvarlo cliccando **[Publish Recap]** per mandarlo sul canale, generare l'immagine per le storie di Instagram e redigere l'articolo per il sito.

### 8. Controlli Generali del Bot
- `/bot_pause`: Mette in pausa la lettura automatica dei messaggi per la creazione di eventi (utile durante lunghe discussioni nel canale).
- `/bot_resume`: Riattiva il bot.
- `/bot_status`: Mostra lo stato attuale del bot (Attivo/In pausa) e la modalità solo Eventbrite.
- `/bot_eventbrite_venue`: Se sono configurate più sedi Eventbrite, mostra i pulsanti per sceglierne una: vale per tutti gli eventi pubblicati su Eventbrite da quel momento (ogni evento mantiene la propria). Riavviando il bot si torna alla sede predefinita.
- `/bot_eventbrite_only_toggle`: Attiva/disattiva la modalità solo Eventbrite: le nuove anteprime non hanno i pulsanti per pubblicare solo su Telegram e la storia Instagram non viene generata.
- `/start`: Presenta il bot e mostra i comandi pubblici (`/event_next`, `/event_subs`); con i link diretti `?start=event_next` e `?start=subs_<id>` apre la lista eventi o gli iscritti di un evento.
- `/event_next [data]`: Mostra la lista di tutti gli eventi di oggi e futuri in ordine cronologico con data e link rapidi. Con una data (`gg-mm-aaaa`, `oggi`, `lunedì`, `mercoledì`, `venerdì`, `sabato`, `domenica`) mostra solo gli eventi di quel giorno; un giorno della settimana indica la prima occorrenza, oggi compreso (es. `/event_next venerdì`). Questo comando è **accessibile anche pubblicamente agli utenti** sia in chat privata col bot che nel gruppo discussione (disattivabile nel gruppo discussione tramite variabile d'ambiente `ALLOW_GROUP_EVENT_NEXT=false` per prevenire spam).

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
