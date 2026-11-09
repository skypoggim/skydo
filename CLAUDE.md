# skydo

Quiz tra colleghi stile Mentimeter/Slido, ma con lo schermo fatto interamente in PowerPoint (es. tabellone tipo ruota della fortuna con lettere che si scoprono slide dopo slide). skydo serve solo a raccogliere le risposte da telefono: chi risponde giusto per primo vince.

## Come funziona

- `index.html`: pagina statica per il telefono, pubblicata su GitHub Pages (repo `skypoggim/skydo`, Pages da `main` root → `https://skypoggim.github.io/skydo/`). Al primo accesso chiede il nome (salvato in localStorage), poi solo campo risposta. Pubblica JSON `{id, name, type: join|answer, answer}` su `ntfy.sh/<topic>`, topic preso da `?t=` nell'URL. Stile coerente con dataday: font Sky Text in `assets/fonts/` (copiato da dataday) e palette chiara di `dataday/css/style.css` (`--primary #3252CC`, `--accent #C83640`, `--text #1C2040`).
- `skydo.py`: genera il topic (`skydo-<random>`), stampa il QR di `<player-url>?t=<topic>` e lo salva in `qr.png` per la slide; ascolta lo stream ntfy.
- Le risposte vengono associate alla domanda per tempo, non per ordine: invio nel terminale = parte la domanda successiva e riparte il timer. `secondi` = arrivo sul PC meno partenza domanda.
- `quiz.json` (in `.gitignore`: il repo è pubblico, le soluzioni non vanno pushate): lista di `{domanda, risposte}` con le risposte accettate, confrontate normalizzando maiuscole/accenti/punteggiatura. Il primo ✓ di ogni domanda vince.
- Output: DataFrame `domanda, nome, risposta, corretta, secondi, ts, id` (`r`), classifica per vittorie e poi tempo (`c`), csv in `results/` all'uscita (`q`).
- Niente server nostro: ntfy fa da canale.

Uso: `python skydo.py [--quiz quiz.json] [--topic NOME]` (topic fisso utile per preparare il QR in anticipo nel ppt).

## Vincoli

- Python dell'env conda `base` (ha `qrcode`, `pandas`, `requests`).
- Topic pubblico: chi lo conosce legge/scrive. Solo per giochi, niente dati sensibili.
- Arrivano solo i messaggi inviati mentre lo script gira.
