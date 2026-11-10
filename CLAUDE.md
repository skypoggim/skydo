# skydo

Quiz tra colleghi stile Mentimeter/Slido, ma con lo schermo fatto interamente in PowerPoint (es. tabellone tipo ruota della fortuna con lettere che si scoprono slide dopo slide). skydo serve solo a raccogliere le risposte da telefono: chi risponde giusto per primo vince.

## I due link

- **Giocatori**: `https://skypoggim.github.io/skydo/` (`index.html`). QR fisso, va nella slide una volta per tutte. Nome chiesto una volta (localStorage), poi solo risposte; all'apertura si ripresenta al conduttore.
- **Conduttore**: `https://skypoggim.github.io/skydo/host.html`. Chiave `HOST_KEY` chiesta una volta (localStorage). QR scaricabile, "▶ Domanda", Live ✓/✗/🏆, Classifica, Giocatori, CSV, Reset.

Dietro c'è `server.py` su Render free (`render.yaml`, `https://skydo.onrender.com`): stdlib senza dipendenze, **una sola partita** in memoria. Env var `HOST_KEY` impostata nella dashboard Render (mai nel repo, che è pubblico). URL del server: costante `SERVER` in `index.html` e `host.html`.

## Come funziona

- API: `POST /msg` (telefoni: join/answer), `GET /msg?since=&key=` (conduttore), `POST /login|/question|/reset` con `{key}`.
- Il server timbra ogni messaggio con ora e numero progressivo: la domanda a cui appartiene una risposta e i `secondi` (ora risposta − ora domanda) dipendono solo dall'orologio del server.
- `epoch` cambia a ogni reset/riavvio: se cambia senza un reset chiesto dal conduttore (Render riavviato), `host.html` tiene risposte e classifica già ricevute e continua.
- Correttezza e classifica sono calcolate in `host.html` da `quiz.json` (`[{domanda, risposte: [...]}]`), pushato nel repo pubblico per semplicità (scelta consapevole). Confronto normalizzando maiuscole/accenti/punteggiatura. Classifica: vittorie (primo ✓ per domanda), a parità meno secondi totali.
- Ricaricando `host.html` la partita viene ricostruita dal server.
- Ntfy.sh scartato: limiti per IP (250 msg/giorno, burst ~60) e in ufficio 100 telefoni escono dallo stesso IP.

## Stile

Coerente con dataday: font Sky Text in `assets/fonts/` (copiato da dataday) e palette chiara di `dataday/css/style.css` (`--primary #3252CC`, `--accent #C83640`, `--text #1C2040`).

## Vincoli

- Render free dorme dopo 15 min senza richieste (risveglio ~1 min): aprire `host.html` qualche minuto prima, il suo polling lo tiene sveglio. Un riavvio svuota il server: a fine partita scaricare il CSV.
- Una partita alla volta.
