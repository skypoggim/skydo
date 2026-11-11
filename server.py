"""Server minimo di skydo (Render): una sola partita in memoria, condotta da chi conosce HOST_KEY.

POST /msg                   messaggio dei telefoni {id, name, type: join|answer, answer}
                            409 se: manca il cognome, nome già preso da un altro id, domanda non partita, già risposto a questa domanda
GET  /msg?since=N&key=K     {epoch, messages}: messaggi con seq > N, solo conduttore
GET  /classifica?id=X       {n, scelte, top: primi 5, me: posizione di X}, pubblica; scelte = n. opzioni (0 = risposta aperta)
GET  /attesa?n=N            {n, scelte} appena la domanda in corso non è più N (long-polling, max WAIT s), pubblica
GET  /quiz?key=K            domande e risposte, solo conduttore
POST /login | /question | /reset   {"key": K[, "n": domanda]}: verifica chiave, avvia domanda, azzera la partita
`epoch` cambia a ogni reset o riavvio, così il conduttore sa che la numerazione è ripartita.
Punti: risposta giusta = da MAX_POINTS (subito) a MIN_POINTS (dopo `tempo` secondi, default DEFAULT_TIME), sbagliata = 0.
Correttezza da quiz.json (Secret File di Render, mai nel repo pubblico): nelle domande aperte sono tollerati
piccoli refusi (vedi _matches); a parità di punti vince chi ha meno secondi totali sulle risposte giuste.
"""
import hmac
import json
import os
import secrets
import re
import threading
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HOST_KEY = os.environ.get("HOST_KEY", "")
MAX_BODY = 2000
MAX_MESSAGES = 50000
MAX_POINTS, MIN_POINTS, DEFAULT_TIME = 1000, 500, 30
WAIT = 25
# su Render il Secret File sta in /etc/secrets, in locale si usa quiz.json accanto al server (ignorato da git)
QUIZ_PATHS = ["/etc/secrets/quiz.json", os.path.join(os.path.dirname(os.path.abspath(__file__)), "quiz.json")]


def _load_quiz():
    for path in QUIZ_PATHS:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    print("ATTENZIONE: quiz.json non trovato", flush=True)
    return []


def _normalize(text):
    text = unicodedata.normalize("NFD", str(text).lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _distance(a, b):
    """Distanza di Levenshtein (lettere inserite, tolte o cambiate)."""
    row = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, char_b in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (char_a != char_b))
    return row[-1]


def _matches(answer, accepted, open_question):
    """Uguali dopo la normalizzazione; nelle domande aperte basta 1 errore ogni 8 lettere (es. 'pesce' per 'pesci')."""
    answer, accepted = _normalize(answer), _normalize(accepted)
    if answer == accepted:
        return True
    return open_question and len(accepted) >= 8 and _distance(answer, accepted) <= len(accepted) // 8


def _score(n, answer, seconds):
    """(corretta, punti) della risposta alla domanda n arrivata dopo `seconds`."""
    if not 0 < n <= len(_game["quiz"]):
        return False, 0
    question = _game["quiz"][n - 1]
    open_question = not question.get("opzioni")
    if not any(_matches(answer, accepted, open_question) for accepted in question["risposte"]):
        return False, 0
    ratio = min(seconds / float(question.get("tempo", DEFAULT_TIME)), 1)
    return True, round(MAX_POINTS - (MAX_POINTS - MIN_POINTS) * ratio)


def _new_game():
    # n = domanda in corso, start = ora del via, answered = (domanda, id) già risposti, names = nome normalizzato -> id,
    # scores = id -> {nome, punti, giuste, secondi}, solved = domande con già una risposta giusta
    return {"epoch": secrets.token_hex(4), "messages": [], "n": 0, "start": None, "answered": set(),
            "names": {}, "ids": {}, "scores": {}, "solved": set(), "quiz": _load_quiz()}


def _ranking():
    return sorted(_game["scores"].items(), key=lambda item: (-item[1]["punti"], item[1]["secondi"]))


_game = _new_game()
_lock = threading.Lock()
_changed = threading.Condition(_lock)  # svegliata a ogni via o reset, per /attesa


def _current():
    n = _game["n"]
    question = _game["quiz"][n - 1] if 0 < n <= len(_game["quiz"]) else {}
    return {"n": n, "scelte": len(question.get("opzioni", []))}


def _is_host(key):
    return bool(HOST_KEY) and hmac.compare_digest(str(key), HOST_KEY)


def _register(player_id, name):
    """Associa il nome all'id; False se il nome è già di un altro giocatore."""
    norm = " ".join(name.lower().split())
    owner = _game["names"].get(norm)
    if owner and owner != player_id:
        return False
    old = _game["ids"].get(player_id)
    if old and old != norm:
        _game["names"].pop(old, None)
    _game["names"][norm] = player_id
    _game["ids"][player_id] = norm
    return True


def _append(payload, now=None):
    if len(_game["messages"]) >= MAX_MESSAGES:
        return None
    seq = len(_game["messages"]) + 1
    _game["messages"].append({"seq": seq, "time": now or time.time(), "message": json.dumps(payload)})
    return seq


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body=None):
        data = json.dumps(body if body is not None else {}).encode()
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204)

    # input malformato (numeri non numeri ecc.): 400 con gli header CORS invece di una connessione chiusa
    def do_GET(self):
        self._safe(self._get)

    def do_POST(self):
        self._safe(self._post)

    def _safe(self, handler):
        try:
            handler()
        except (ValueError, TypeError, KeyError):
            self._send(400)

    def _get(self):
        url = urlparse(self.path)
        if url.path == "/":
            return self._send(200, {"status": "ok"})
        query = parse_qs(url.query)
        if url.path == "/classifica":
            player_id = query.get("id", [""])[0]
            with _lock:
                ranking = [{"pos": i + 1, "nome": score["nome"], "punti": score["punti"], "id": pid}
                           for i, (pid, score) in enumerate(_ranking())]
                current = _current()
            me = next((row for row in ranking if row["id"] == player_id), None)
            for row in ranking:
                row.pop("id")
            return self._send(200, {**current, "top": ranking[:5], "me": me})
        if url.path == "/attesa":
            seen = int(query.get("n", ["0"])[0] or 0)
            with _changed:
                epoch = _game["epoch"]
                _changed.wait_for(lambda: _game["n"] != seen or _game["epoch"] != epoch, timeout=WAIT)
                return self._send(200, _current())
        if url.path not in ("/msg", "/quiz"):
            return self._send(404)
        if not _is_host(query.get("key", [""])[0]):
            return self._send(403)
        if url.path == "/quiz":
            return self._send(200, {"quiz": _game["quiz"]})
        since = int(query.get("since", ["0"])[0] or 0)
        with _lock:
            body = {"epoch": _game["epoch"], "messages": _game["messages"][since:]}
        self._send(200, body)

    def _post(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        if not 0 < length <= MAX_BODY:
            return self._send(400)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except ValueError:
            return self._send(400)
        if not isinstance(payload, dict):
            return self._send(400)
        with _lock:
            if path == "/msg":
                raw_answer, raw_domanda = payload.get("answer", ""), payload.get("domanda")
                player_id, name = str(payload.get("id", ""))[:40], " ".join(str(payload.get("name", "")).split())[:40]
                if payload.get("type") not in ("join", "answer") or not player_id or not name:
                    return self._send(400)
                if len(name.split()) < 2:
                    return self._send(409, {"error": "full_name"})
                if not _register(player_id, name):
                    return self._send(409, {"error": "name_taken"})
                n, now = _game["n"], time.time()
                score = _game["scores"].setdefault(player_id, {"punti": 0, "giuste": 0, "secondi": 0.0})
                score["nome"] = name
                payload = {"type": payload["type"], "id": player_id, "name": name}
                if payload["type"] == "answer":
                    if not n:
                        return self._send(409, {"error": "not_started"})
                    if raw_domanda and raw_domanda != n:
                        # il telefono rispondeva a una domanda già superata dal via successivo
                        return self._send(409, {"error": "stale", "domanda": n})
                    if (n, player_id) in _game["answered"]:
                        return self._send(409, {"error": "already_answered", "domanda": n})
                    _game["answered"].add((n, player_id))
                    answer = str(raw_answer)[:200]
                    seconds = round(now - (_game["start"] or now), 3)
                    correct, points = _score(n, answer, seconds)
                    first = correct and n not in _game["solved"]
                    if correct:
                        _game["solved"].add(n)
                        score.update(punti=score["punti"] + points, giuste=score["giuste"] + 1,
                                     secondi=round(score["secondi"] + seconds, 3))
                    payload.update(answer=answer, domanda=n, corretta=correct, secondi=seconds, punti=points, primo=first)
                seq = _append(payload, now)
                return self._send(200, {"seq": seq, "domanda": n}) if seq else self._send(429)
            if path not in ("/login", "/question", "/reset"):
                return self._send(404)
            if not _is_host(payload.get("key", "")):
                return self._send(403, {"error": "chiave errata" if HOST_KEY else "HOST_KEY non impostata sul server"})
            if path == "/question":
                # il conduttore manda il numero, così resta allineato anche dopo un riavvio del server
                _game["n"] = int(payload.get("n") or _game["n"] + 1)
                _game["start"] = time.time()
                _append({"type": "question", "domanda": _game["n"]}, _game["start"])
                _changed.notify_all()
            elif path == "/reset":
                _game.update(_new_game())
                _changed.notify_all()
            self._send(200, {"epoch": _game["epoch"]})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"skydo server su :{port}" + ("" if HOST_KEY else " (ATTENZIONE: HOST_KEY non impostata)"), flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.daemon_threads = True
    server.serve_forever()
