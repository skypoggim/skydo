"""skydo da terminale (per prove/analisi; dal vivo si usa host.html): risposte via server.py in un DataFrame.

Terminale:  python skydo.py [--quiz quiz.json] [--topic NOME --key CHIAVE] [--player-url URL] [--server URL]
  invio = parte la domanda successiva, r = risultati, c = classifica, q = esci (salva il csv in results/)
Notebook:   import skydo as q; q.start(); q.next_question(); ...; q.df()
"""
import argparse
import json
import re
import secrets
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd
import qrcode
import requests

SERVER_URL = "https://skydo.onrender.com"
PLAYER_URL = "https://skypoggim.github.io/skydo/"
HERE = Path(__file__).parent
COLUMNS = ["domanda", "nome", "risposta", "corretta", "secondi", "ts", "id"]

_answers = []
_players = {}
_quiz = []
_question = {"n": 0, "start": time.time(), "winner": None}
_session = {"server": SERVER_URL, "topic": None, "key": None}


def df():
    return pd.DataFrame(_answers, columns=COLUMNS)


def classifica():
    """Vittorie (primo a rispondere giusto) per giocatore, a parità vince chi è stato più rapido."""
    correct = df()[lambda frame: frame["corretta"] == True]  # noqa: E712 (None = domanda senza soluzioni)
    winners = correct.sort_values("secondi").drop_duplicates("domanda")
    return (
        winners.groupby("nome")
        .agg(vittorie=("domanda", "count"), secondi_totali=("secondi", "sum"))
        .sort_values(["vittorie", "secondi_totali"], ascending=[False, True])
        .reset_index()
    )


def _normalize(text):
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _is_correct(n, answer):
    if not 1 <= n <= len(_quiz):
        return None
    return _normalize(answer) in {_normalize(accepted) for accepted in _quiz[n - 1]["risposte"]}


def next_question():
    """Segna sul server l'inizio della domanda successiva: le risposte arrivate dopo valgono per lei."""
    requests.post(f"{_session['server']}/{_session['topic']}", json={"type": "question", "key": _session["key"]}, timeout=60).raise_for_status()
    return _question["n"] + 1


def _handle(message, arrived, verbose):
    """Smista un messaggio; ordine e tempi sono quelli del server, uguali per tutti."""
    try:
        payload = json.loads(message)
    except ValueError:
        payload = {"type": "answer", "answer": message}
    player_id = payload.get("id", "?")
    name = payload.get("name") or "?"
    if payload.get("type") == "question":
        _question.update(n=_question["n"] + 1, start=arrived, winner=None)
        return
    _players[player_id] = name
    if payload.get("type") == "join":
        if verbose:
            print(f"+ {name} si è iscritto ({len(_players)} giocatori)", flush=True)
        return
    n, answer = _question["n"], payload.get("answer", "")
    seconds = round(arrived - _question["start"], 3)
    correct = _is_correct(n, answer)
    _answers.append((n, name, answer, correct, seconds, datetime.fromtimestamp(arrived), player_id))
    if not verbose:
        return
    mark = {True: "✓", False: "✗", None: "·"}[correct]
    first = ""
    if correct and _question["winner"] is None:
        _question["winner"] = name
        first = "   🏆 PRIMO!"
    print(f"  {mark} D{n}  {seconds:7.3f}s  {name}: {answer}{first}", flush=True)


def _listen(verbose, every=0.3):
    """Interroga il server ogni `every` secondi per i messaggi nuovi della sessione."""
    since = 0
    while True:
        try:
            resp = requests.get(f"{_session['server']}/{_session['topic']}", params={"since": since, "key": _session["key"]}, timeout=60)
            for event in resp.json():
                since = event["seq"]
                _handle(event["message"], event["time"], verbose)
        except (requests.RequestException, ValueError):
            pass
        time.sleep(every)


def load_quiz(path):
    """Carica le domande: lista di {"domanda": str, "risposte": [str, ...]}."""
    _quiz[:] = json.loads(Path(path).read_text())
    return _quiz


def start(player_url=PLAYER_URL, topic=None, key=None, server=SERVER_URL, verbose=True):
    """Sveglia il server, crea (o riprende) la sessione, avvia l'ascolto e stampa il QR della pagina player."""
    topic = topic or f"skydo-{secrets.token_hex(3)}"
    _session.update(server=server.rstrip("/"), topic=topic, key=key or secrets.token_hex(8))
    print(f"Sveglio il server {_session['server']} (su Render free può volerci ~1 min)...", flush=True)
    requests.get(_session["server"], timeout=120).raise_for_status()
    requests.post(f"{_session['server']}/{topic}/host", json={"key": _session["key"]}, timeout=60).raise_for_status()
    print(f"Sessione {topic}, chiave {_session['key']} (per riprenderla: --topic {topic} --key {_session['key']})")
    threading.Thread(target=_listen, args=(verbose,), daemon=True).start()
    url = f"{player_url}?t={topic}"
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.print_ascii(invert=True)
    qr.make_image().save(HERE / "qr.png")
    print(url, "\n(QR salvato anche in qr.png, da mettere nella slide)", flush=True)
    return topic


def _save():
    out = HERE / "results" / f"skydo_{datetime.now():%Y%m%d_%H%M%S}.csv"
    out.parent.mkdir(exist_ok=True)
    df().to_csv(out, index=False)
    print(f"Salvato {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiz", default=HERE / "quiz.json", help="json con domande e risposte accettate")
    parser.add_argument("--topic", help="sessione (default: casuale)")
    parser.add_argument("--key", help="chiave della sessione, per riprenderne una esistente")
    parser.add_argument("--player-url", default=PLAYER_URL, help="URL pubblico di index.html (GitHub Pages)")
    parser.add_argument("--server", default=SERVER_URL, help="URL di server.py (Render)")
    args = parser.parse_args()
    if Path(args.quiz).exists():
        print(f"Quiz: {len(load_quiz(args.quiz))} domande da {args.quiz}")
    start(args.player_url, args.topic, args.key, args.server)
    print("\ninvio = domanda successiva | r = risultati | c = classifica | q = esci\n")
    try:
        while True:
            cmd = input().strip().lower()
            if cmd == "q":
                break
            if cmd == "r":
                print(df().sort_values(["domanda", "secondi"]).to_string(index=False))
            elif cmd == "c":
                print(classifica().to_string(index=False))
            elif _quiz and _question["n"] >= len(_quiz):
                print("Domande finite: c = classifica, q = esci")
            else:
                n = next_question()
                text = f": {_quiz[n - 1]['domanda']}" if _quiz else ""
                print(f"=== Domanda {n} partita{text} ===", flush=True)
    except (KeyboardInterrupt, EOFError):
        pass
    _save()
