"""Server minimo di skydo (gira su Render): riceve i messaggi dei telefoni e li rende al conduttore.

POST /<sessione>/host     {"key": K}: crea la sessione con chiave K (idempotente con la stessa K)
POST /<sessione>          messaggio dei telefoni (join/answer); "question" solo con la chiave
GET  /<sessione>?since=N&key=K   messaggi con seq > N in ordine di arrivo, solo per il conduttore
Tutto in memoria: un riavvio azzera le sessioni.
"""
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MAX_BODY = 2000
MAX_MESSAGES = 20000
SESSION_TTL = 24 * 3600
PATH_RE = re.compile(r"^/([A-Za-z0-9_-]{1,64})(/host)?$")

_sessions = {}
_lock = threading.Lock()


def _cleanup(now):
    for name in [name for name, session in _sessions.items() if now - session["last"] > SESSION_TTL]:
        del _sessions[name]


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
        match = PATH_RE.match(url.path)
        if not match or match[2]:
            return self._send(404)
        query = parse_qs(url.query)
        since = int(query.get("since", ["0"])[0] or 0)
        with _lock:
            session = _sessions.get(match[1])
            if not session:
                return self._send(404, {"error": "sessione inesistente"})
            if query.get("key", [""])[0] != session["key"]:
                return self._send(403)
            body = [message for message in session["messages"] if message["seq"] > since]
        self._send(200, body)

    def do_POST(self):
        match = PATH_RE.match(urlparse(self.path).path)
        length = int(self.headers.get("Content-Length", 0))
        if not match or not 0 < length <= MAX_BODY:
            return self._send(400)
        text = self.rfile.read(length).decode("utf-8", "replace")
        try:
            payload = json.loads(text)
        except ValueError:
            payload = {}
        payload = payload if isinstance(payload, dict) else {}
        now = time.time()
        with _lock:
            _cleanup(now)
            session = _sessions.get(match[1])
            if match[2]:
                key = str(payload.get("key", ""))
                if len(key) < 8:
                    return self._send(400)
                if session and session["key"] != key:
                    return self._send(403, {"error": "sessione già usata"})
                _sessions.setdefault(match[1], {"key": key, "messages": [], "last": now})
                return self._send(200, {"ok": True})
            if not session:
                return self._send(404, {"error": "sessione inesistente"})
            if payload.get("type") == "question" and payload.get("key") != session["key"]:
                return self._send(403)
            if len(session["messages"]) >= MAX_MESSAGES:
                return self._send(429)
            session["last"] = now
            payload.pop("key", None)
            seq = len(session["messages"]) + 1
            session["messages"].append({"seq": seq, "time": now, "message": json.dumps(payload) if payload else text})
        self._send(200, {"seq": seq})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"skydo server su :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
