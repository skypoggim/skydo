"""skydo: QR code per far rispondere i colleghi da telefono, risposte via ntfy.sh in un DataFrame.

Terminale:  python skydo.py --player-url https://skypoggim.github.io/skydo/ [--topic NOME]
  invio = parte la domanda successiva, r = risultati, q = esci (salva il csv in results/)
Notebook:   import skydo as q; q.start(player_url); q.next_question(); ...; q.df()
"""
import argparse
import json
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import qrcode
import requests

NTFY = "https://ntfy.sh"
COLUMNS = ["domanda", "nome", "risposta", "secondi", "ts", "id"]

_answers = []
_players = {}
_question = {"n": 0, "start": time.time()}


def df():
    return pd.DataFrame(_answers, columns=COLUMNS)


def next_question():
    """Da adesso le risposte valgono per la domanda successiva; il timer riparte."""
    _question["n"] += 1
    _question["start"] = time.time()
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
    seconds = round(arrived - _question["start"], 3)
    row = (_question["n"], name, payload.get("answer", ""), seconds, datetime.fromtimestamp(arrived), player_id)
    _answers.append(row)
    if verbose:
        print(f"  D{row[0]}  {seconds:7.3f}s  {name}: {row[2]}", flush=True)


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


def start(player_url, topic=None, verbose=True):
    """Avvia l'ascolto in background e stampa il QR della pagina player per il topic."""
    topic = topic or f"skydo-{secrets.token_urlsafe(9)}"
    threading.Thread(target=_listen, args=(topic, verbose), daemon=True).start()
    url = f"{player_url}?t={topic}"
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.print_ascii(invert=True)
    qr.make_image().save(Path(__file__).parent / "qr.png")
    print(url, "\n(QR salvato anche in qr.png, da mettere nella slide)", flush=True)
    return topic


def _save():
    out = Path(__file__).parent / "results" / f"skydo_{datetime.now():%Y%m%d_%H%M%S}.csv"
    out.parent.mkdir(exist_ok=True)
    df().to_csv(out, index=False)
    print(f"Salvato {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--player-url", required=True, help="URL pubblico di index.html (GitHub Pages)")
    parser.add_argument("--topic", help="topic ntfy (default: casuale)")
    args = parser.parse_args()
    start(args.player_url, args.topic)
    print("\ninvio = domanda successiva | r = risultati | q = esci\n")
    try:
        while True:
            cmd = input().strip().lower()
            if cmd == "q":
                break
            if cmd == "r":
                print(df().sort_values(["domanda", "secondi"]).to_string(index=False))
            else:
                print(f"=== Domanda {next_question()} partita ===", flush=True)
    except (KeyboardInterrupt, EOFError):
        pass
    _save()
