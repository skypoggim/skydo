"""skydo: QR code per far rispondere i colleghi da telefono, risposte via ntfy.sh in un DataFrame.

Terminale:  python skydo.py [--quiz quiz.json] [--topic NOME] [--player-url URL]
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

NTFY = "https://ntfy.sh"
PLAYER_URL = "https://skypoggim.github.io/skydo/"
HERE = Path(__file__).parent
COLUMNS = ["domanda", "nome", "risposta", "corretta", "secondi", "ts", "id"]

_answers = []
_players = {}
_quiz = []
_question = {"n": 0, "start": time.time(), "winner": None}


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
    """Da adesso le risposte valgono per la domanda successiva; il timer riparte."""
    _question.update(n=_question["n"] + 1, start=time.time(), winner=None)
    return _question["n"]


def _handle(message, verbose):
    arrived = time.time()
    try:
        payload = json.loads(message)
    except ValueError:
        payload = {"type": "answer", "answer": message}
    player_id = payload.get("id", "?")
    name = payload.get("name") or "?"
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


def _listen(topic, verbose):
    """Resta in ascolto sullo stream JSON del topic (si riconnette se cade)."""
    while True:
        try:
            with requests.get(f"{NTFY}/{topic}/json", stream=True, timeout=90) as resp:
                for line in resp.iter_lines():
                    event = json.loads(line) if line else {}
                    if event.get("event") == "message":
                        _handle(event.get("message", ""), verbose)
        except requests.RequestException:
            pass


def load_quiz(path):
    """Carica le domande: lista di {"domanda": str, "risposte": [str, ...]}."""
    _quiz[:] = json.loads(Path(path).read_text())
    return _quiz


def start(player_url=PLAYER_URL, topic=None, verbose=True):
    """Avvia l'ascolto in background e stampa il QR della pagina player per il topic."""
    topic = topic or f"skydo-{secrets.token_urlsafe(9)}"
    threading.Thread(target=_listen, args=(topic, verbose), daemon=True).start()
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
    parser.add_argument("--topic", help="topic ntfy (default: casuale)")
    parser.add_argument("--player-url", default=PLAYER_URL, help="URL pubblico di index.html (GitHub Pages)")
    args = parser.parse_args()
    if Path(args.quiz).exists():
        print(f"Quiz: {len(load_quiz(args.quiz))} domande da {args.quiz}")
    start(args.player_url, args.topic)
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
