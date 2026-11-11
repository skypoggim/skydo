"""Stress test di skydo: N giocatori finti contro il server vero, come durante l'evento.

Ogni giocatore si iscrive, resta in attesa del via su /attesa, aggiorna /classifica ogni 3 s e risponde
a ogni domanda dopo qualche secondo (metà giuste). Il conduttore finto legge /msg ogni 0,5 s.
Misura i tempi di risposta del server e conta gli errori. Fa RESET della partita all'inizio e alla fine:
mai durante l'evento.

    HOST_KEY=... python stress.py [--server URL] [--players 100] [--questions 3] [--pause 20]
"""
import argparse
import json
import os
import random
import statistics
import threading
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--server", default="https://skydo.onrender.com")
parser.add_argument("--players", type=int, default=100)
parser.add_argument("--questions", type=int, default=3)
parser.add_argument("--pause", type=float, default=20, help="secondi tra una domanda e l'altra")
args = parser.parse_args()
KEY = os.environ.get("HOST_KEY") or exit("Imposta HOST_KEY")

times = {}    # endpoint -> durate in s
errors = {}   # endpoint -> {errore: conteggio}
wakeups = []  # ritardo tra il via e il risveglio di ogni /attesa
lock = threading.Lock()
stop = threading.Event()
started = {}  # domanda -> ora del via


def call(endpoint, path, body=None, timeout=40):
    request = urllib.request.Request(args.server + path, data=json.dumps(body).encode() if body else None,
                                     method="POST" if body else "GET")
    start = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data = json.load(resp)
        outcome = None
    except urllib.error.HTTPError as error:
        data = json.loads(error.read() or b"{}")
        outcome = None if error.code == 409 else f"HTTP {error.code}"
    except Exception as error:  # timeout, connessione chiusa, ...
        data, outcome = {}, type(error).__name__
    with lock:
        times.setdefault(endpoint, []).append(time.time() - start)
        if outcome:
            errors.setdefault(endpoint, {}).setdefault(outcome, 0)
            errors[endpoint][outcome] += 1
    return data


def player(i, quiz):
    player_id, name = f"stress{i:03d}", f"Stress Test{i:03d}"
    call("join", "/msg", {"id": player_id, "name": name, "type": "join"})
    seen = 0

    def board():
        while not stop.is_set():
            call("classifica", f"/classifica?id={player_id}")
            stop.wait(3)
    threading.Thread(target=board, daemon=True).start()

    while not stop.is_set():
        data = call("attesa", f"/attesa?n={seen}")
        n = data.get("n", seen)
        if n == seen or not n:
            continue
        seen = n
        if n in started:
            with lock:
                wakeups.append(time.time() - started[n])
        time.sleep(random.uniform(1, 10))
        question = quiz[n - 1] if n <= len(quiz) else {"risposte": ["x"]}
        answer = question["risposte"][0] if random.random() < .5 else "sbagliata"
        call("risposta", "/msg", {"id": player_id, "name": name, "type": "answer", "answer": answer, "domanda": n})


def host():
    since = 0
    while not stop.is_set():
        data = call("conduttore", f"/msg?since={since}&key={KEY}")
        since += len(data.get("messages", []))
        stop.wait(.5)


def percentiles(values):
    values = sorted(values)
    pick = lambda q: values[min(len(values) - 1, int(q * len(values)))]
    return f"n={len(values):5d}  mediana {statistics.median(values):.2f}s  p95 {pick(.95):.2f}s  max {values[-1]:.2f}s"


print(f"Sveglio {args.server}…")
call("sveglia", "/", timeout=120)
call("reset", "/reset", {"key": KEY})
quiz = call("quiz", f"/quiz?key={KEY}").get("quiz") or exit("Chiave errata o quiz vuoto")
threads = [threading.Thread(target=player, args=(i, quiz), daemon=True) for i in range(args.players)]
for thread in threads:
    thread.start()
    time.sleep(.02)
threading.Thread(target=host, daemon=True).start()
time.sleep(5)
print(f"{args.players} giocatori collegati")

for n in range(1, min(args.questions, len(quiz)) + 1):
    started[n] = time.time()
    call("via", "/question", {"key": KEY, "n": n})
    print(f"Domanda {n} avviata, attendo {args.pause:.0f}s")
    time.sleep(args.pause)

stop.set()
top = call("classifica", "/classifica?id=")["top"]
call("reset", "/reset", {"key": KEY})

print("\nTempi di risposta del server")
for endpoint in ("join", "risposta", "classifica", "conduttore", "via"):
    if times.get(endpoint):
        print(f"  {endpoint:11s} {percentiles(times[endpoint])}")
if wakeups:
    print(f"  {'risveglio':11s} {percentiles(wakeups)}   (dal via al telefono che lo vede)")
print("\nErrori:", json.dumps(errors) if errors else "nessuno")
print("Primi in classifica:", ", ".join(f"{row['nome']} {row['punti']}" for row in top[:3]))
print("Partita azzerata.")
