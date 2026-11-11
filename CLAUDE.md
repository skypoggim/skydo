# skydo

Quiz tra colleghi stile Mentimeter/Slido, ma con lo schermo fatto interamente in PowerPoint (es. tabellone tipo ruota della fortuna con lettere che si scoprono slide dopo slide). skydo serve solo a raccogliere le risposte da telefono: chi risponde giusto per primo vince.

## I due link

- **Giocatori**: `https://skypoggim.github.io/skydo/` (`index.html`). QR fisso, va nella slide una volta per tutte. Nome e cognome chiesti una volta (localStorage, almeno due parole), poi solo risposte e classifica (primi 5, poi `⋮` e la propria posizione); all'apertura si ripresenta al conduttore.
- **Conduttore**: `https://skypoggim.github.io/skydo/host.html`. Chiave `HOST_KEY` chiesta una volta (localStorage). QR scaricabile, "▶ Domanda", Live ✓/✗/🏆 con punti, Classifica completa, CSV, Reset.

Dietro c'è `server.py` su Render free (`render.yaml`, `https://skydo.onrender.com`): stdlib senza dipendenze, **una sola partita** in memoria. Env var `HOST_KEY` impostata nella dashboard Render (mai nel repo, che è pubblico). URL del server: costante `SERVER` in `index.html` e `host.html`.

## Come funziona

- API: `POST /msg` (telefoni: join/answer), `GET /msg?since=&key=` (conduttore), `GET /classifica?id=` e `GET /attesa?n=` (telefoni, pubbliche), `GET /quiz?key=` (conduttore), `POST /login|/question|/reset` con `{key}`.
- Regole applicate dal server (409 + messaggio sul telefono): nome e cognome obbligatori (almeno due parole), nomi unici (case/spazi ignorati, il nome resta di chi l'ha preso per primo fino al reset), niente risposte prima della prima domanda, una sola risposta per giocatore per domanda (vale la prima). Una risposta vale per la domanda in corso quando arriva: chi salta la domanda 1 e risponde dopo il via della 2 risponde alla 2. `/question` riceve il numero di domanda dal conduttore, così il server resta allineato anche dopo un riavvio.
- Il server timbra ogni messaggio con ora e numero progressivo: la domanda a cui appartiene una risposta e i `secondi` (ora risposta − ora domanda) dipendono solo dall'orologio del server.
- `epoch` cambia a ogni reset/riavvio: se cambia senza un reset chiesto dal conduttore (Render riavviato), `host.html` tiene risposte e classifica già ricevute, rimanda al server la domanda in corso (il tempo dei punti riparte da lì) e ignora le risposte doppie, perché il server ha dimenticato chi aveva già risposto.
- Indicatore server in alto a destra in `host.html`: grigio = si sta svegliando (riprova per 2,5 min), verde = il polling risponde, rosso = nessuna risposta da 3 s. Toccandolo da rosso riprova a svegliarlo, con link alla dashboard Render per riavviarlo a mano.
- Punteggio calcolato dal server (così telefoni e conduttore vedono gli stessi numeri) da `quiz.json` (`[{domanda, risposte: [...], opzioni?, tempo?}]`). Il file **non sta nel repo** (pubblico, e GitHub Pages lo servirebbe a chiunque): è ignorato da git ed è caricato come **Secret File** su Render (Environment → Secret Files → `quiz.json`, letto da `/etc/secrets/quiz.json`). In locale il server usa `quiz.json` accanto a sé. `host.html` lo legge da `/quiz` con la chiave. Il server lo rilegge a ogni reset. Confronto normalizzando maiuscole/accenti/punteggiatura; nelle domande aperte con risposta di almeno 8 lettere è tollerato 1 errore ogni 8 lettere ("piglia pesce", "camberra"), numeri e lettere A/B/C/D vanno esatti. Risposta giusta: 1000 punti se immediata, che scendono in modo lineare fino a 500 a `tempo` secondi dal via (default 30) e poi restano 500; sbagliata 0. Classifica: punti, a parità meno secondi totali sulle risposte giuste. 🏆 = primo ✓ della domanda, solo segnalato. Costanti in cima a `server.py`.
- Domande a scelta multipla: in `quiz.json` `opzioni: [...]` e `risposte: ["B"]` (lettera). Il testo resta sul PPT e su `host.html` (opzioni con la giusta in verde); il telefono legge da `/classifica` solo quante opzioni ha la domanda in corso (`scelte`) e mostra i pulsanti A/B/C/D, altrimenti il campo di testo. Il telefono resta in attesa su `/attesa` (long-polling, il server risponde appena parte la domanda successiva, max 25 s), quindi il cambio è istantaneo; la classifica si aggiorna ogni 3 s. Ogni risposta porta la `domanda` che il telefono crede in corso e, se nel frattempo è partita la successiva, il server la rifiuta (409 `stale`) invece di assegnarla alla domanda sbagliata.
- Ricaricando `host.html` la partita viene ricostruita dal server.
- Ntfy.sh scartato: limiti per IP (250 msg/giorno, burst ~60) e in ufficio 100 telefoni escono dallo stesso IP.

## Stile

Coerente con dataday: font Sky Text in `assets/fonts/` (copiato da dataday) e palette chiara di `dataday/css/style.css` (`--primary #3252CC`, `--accent #C83640`, `--text #1C2040`).

## Vincoli

- Render free dorme dopo 15 min senza richieste (risveglio ~1 min): aprire `host.html` qualche minuto prima, il suo polling lo tiene sveglio. Un riavvio svuota il server: `host.html` tiene la sua classifica, ma quella sui telefoni riparte da zero; a fine partita scaricare il CSV.
- Una partita alla volta.
