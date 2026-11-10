"""Server minimo di skydo (Render): una sola partita in memoria, condotta da chi conosce HOST_KEY.

POST /msg                   messaggio dei telefoni {id, name, type: join|answer, answer}
                            409 se: manca il cognome, nome già preso da un altro id, domanda non partita, già risposto a questa domanda
GET  /msg?since=N&key=K     {epoch, messages}: messaggi con seq > N, solo conduttore
GET  /classifica?id=X       {n, scelte, top: primi 5, me: posizione di X}, pubblica; scelte = n. opzioni (0 = risposta aperta)
POST /login | /question | /reset   {"key": K[, "n": domanda]}: verifica chiave, avvia domanda, azzera la partita
`epoch` cambia a ogni reset o riavvio, così il conduttore sa che la numerazione è ripartita.
Punti: risposta giusta = da MAX_POINTS (subito) a MIN_POINTS (dopo `tempo` secondi, default DEFAULT_TIME), sbagliata = 0.
Correttezza da quiz.json; a parità di punti vince chi ha meno secondi totali sulle risposte giuste.
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
QUIZ_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quiz.json")


def _load_quiz():
    with open(QUIZ_PATH, encoding="utf-8") as f:
        return json.load(f)


def _normalize(text):
    text = unicodedata.normalize("NFD", str(text).lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _score(n, answer, seconds):
    """(corretta, punti) della risposta alla domanda n arrivata dopo `seconds`."""
    if not 0 < n <= len(_game["quiz"]):
        return False, 0
    question = _game["quiz"][n - 1]
    if _normalize(answer) not in {_normalize(accepted) for accepted in question["risposte"]}:
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

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            return self._send(200, {"status": "ok"})
        query = parse_qs(url.query)
        if url.path == "/classifica":
            player_id = query.get("id", [""])[0]
            with _lock:
                ranking = [{"pos": i + 1, "nome": score["nome"], "punti": score["punti"], "id": pid}
                           for i, (pid, score) in enumerate(_ranking())]
                n = _game["n"]
                question = _game["quiz"][n - 1] if 0 < n <= len(_game["quiz"]) else {}
            me = next((row for row in ranking if row["id"] == player_id), None)
            for row in ranking:
                row.pop("id")
            return self._send(200, {"n": n, "scelte": len(question.get("opzioni", [])), "top": ranking[:5], "me": me})
        if url.path != "/msg":
            return self._send(404)
        if not _is_host(query.get("key", [""])[0]):
            return self._send(403)
        since = int(query.get("since", ["0"])[0] or 0)
        with _lock:
            body = {"epoch": _game["epoch"], "messages": _game["messages"][since:]}
        self._send(200, body)

    def do_POST(self):
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
            elif path == "/reset":
                _game.update(_new_game())
            self._send(200, {"epoch": _game["epoch"]})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"skydo server su :{port}" + ("" if HOST_KEY else " (ATTENZIONE: HOST_KEY non impostata)"), flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
