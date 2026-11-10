"""Server minimo di skydo (Render): una sola partita in memoria, condotta da chi conosce HOST_KEY.

POST /msg                   messaggio dei telefoni {id, name, type: join|answer, answer}
                            409 se: nome già preso da un altro id, domanda non partita, già risposto a questa domanda
GET  /msg?since=N&key=K     {epoch, messages}: messaggi con seq > N, solo conduttore
POST /login | /question | /reset   {"key": K[, "n": domanda]}: verifica chiave, avvia domanda, azzera la partita
`epoch` cambia a ogni reset o riavvio, così il conduttore sa che la numerazione è ripartita.
"""
import hmac
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HOST_KEY = os.environ.get("HOST_KEY", "")
MAX_BODY = 2000
MAX_MESSAGES = 50000


def _new_game():
    # n = domanda in corso, answered = (domanda, id) già risposti, names = nome normalizzato -> id
    return {"epoch": secrets.token_hex(4), "messages": [], "n": 0, "answered": set(), "names": {}, "ids": {}}


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


def _append(payload):
    if len(_game["messages"]) >= MAX_MESSAGES:
        return None
    seq = len(_game["messages"]) + 1
    _game["messages"].append({"seq": seq, "time": time.time(), "message": json.dumps(payload)})
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
        if url.path != "/msg":
            return self._send(404)
        query = parse_qs(url.query)
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
                player_id, name = str(payload.get("id", ""))[:40], str(payload.get("name", "")).strip()[:30]
                if payload.get("type") not in ("join", "answer") or not player_id or not name:
                    return self._send(400)
                if not _register(player_id, name):
                    return self._send(409, {"error": "name_taken"})
                n = _game["n"]
                if payload["type"] == "answer":
                    if not n:
                        return self._send(409, {"error": "not_started"})
                    if (n, player_id) in _game["answered"]:
                        return self._send(409, {"error": "already_answered", "domanda": n})
                    _game["answered"].add((n, player_id))
                payload.pop("key", None)
                seq = _append(payload)
                return self._send(200, {"seq": seq, "domanda": n}) if seq else self._send(429)
            if path not in ("/login", "/question", "/reset"):
                return self._send(404)
            if not _is_host(payload.get("key", "")):
                return self._send(403, {"error": "chiave errata" if HOST_KEY else "HOST_KEY non impostata sul server"})
            if path == "/question":
                # il conduttore manda il numero, così resta allineato anche dopo un riavvio del server
                _game["n"] = int(payload.get("n") or _game["n"] + 1)
                _append({"type": "question"})
            elif path == "/reset":
                _game.update(_new_game())
            self._send(200, {"epoch": _game["epoch"]})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"skydo server su :{port}" + ("" if HOST_KEY else " (ATTENZIONE: HOST_KEY non impostata)"), flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
