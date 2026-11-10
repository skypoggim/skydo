# skydo

Quiz tra colleghi stile Mentimeter/Slido, ma con lo schermo fatto interamente in PowerPoint (es. tabellone tipo ruota della fortuna con lettere che si scoprono slide dopo slide). skydo serve solo a raccogliere le risposte da telefono: chi risponde giusto per primo vince.

## Pezzi

| File | Dove gira | Cosa fa |
|---|---|---|
| `index.html` | GitHub Pages (`https://skypoggim.github.io/skydo/?t=<sessione>`) | pagina giocatore: nome una volta (localStorage), poi solo risposte |
| `host.html` | GitHub Pages (`.../skydo/host.html`), da laptop o telefono | pagina conduttore: legge `quiz.json` dal sito, crea la sessione, mostra/scarica il QR, "Domanda successiva", live ✓/✗/🏆, classifica, CSV |
| `server.py` | Render free (`render.yaml`), `https://skydo.onrender.com` | stdlib senza dipendenze, sessioni in memoria |
| `skydo.py` | terminale | stesso ruolo di `host.html`, per prove e analisi in pandas |

URL del server: costante `SERVER` in `index.html` e `host.html`, `SERVER_URL` in `skydo.py`.

## Come funziona

- Il conduttore crea la sessione con una chiave segreta (`POST /<sessione>/host`). I telefoni pubblicano `{id, name, type: join|answer, answer}` su `POST /<sessione>`; leggere (`GET /<sessione>?since=&key=`) e lanciare le domande (`type: question`) richiede la chiave, così un giocatore non può spiare le risposte altrui.
- Il server timbra ogni messaggio con ora e numero progressivo: la domanda a cui appartiene una risposta e i `secondi` (ora risposta − ora domanda) dipendono solo dall'orologio del server.
- Correttezza e classifica sono calcolate lato conduttore. Il quiz è `quiz.json` (`[{domanda, risposte: [...]}]`), pushato nel repo pubblico per semplicità (scelta consapevole: soluzioni leggibili da chi le cerca, da rivedere se serve); per cambiarlo si modifica e si fa push. Confronto normalizzando maiuscole/accenti/punteggiatura.
- Classifica: vittorie (primo ✓ per domanda), a parità meno secondi totali.
- `host.html` salva sessione e chiave in localStorage: ricaricando la pagina rilegge tutto dal server. `skydo.py` idem con `--topic` + `--key`.
- Ntfy.sh scartato: limiti per IP (250 msg/giorno, burst ~60) e in ufficio 100 telefoni escono dallo stesso IP.

## Stile

Coerente con dataday: font Sky Text in `assets/fonts/` (copiato da dataday) e palette chiara di `dataday/css/style.css` (`--primary #3252CC`, `--accent #C83640`, `--text #1C2040`).

## Vincoli

- Render free dorme dopo 15 min senza richieste (risveglio ~1 min, `host.html` lo sveglia all'apertura); il polling del conduttore lo tiene sveglio durante il gioco. Un riavvio azzera le sessioni: scaricare il CSV a fine partita.
- Sessioni scadono dopo 24h di inattività.
- `skydo.py` usa l'env conda `base` (`qrcode`, `pandas`, `requests`).
