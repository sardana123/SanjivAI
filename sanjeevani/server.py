"""Zero-dependency HTTP server: JSON API + single-page UI."""
from __future__ import annotations

import hmac
import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .companion import Companion
from .config import Settings

log = logging.getLogger("sanjeevani.server")
STATIC = Path(__file__).parent / "static"
MAX_BODY = 64 * 1024


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


def make_handler(companion: Companion, settings: Settings):
    c = companion

    def body_of(h) -> dict:
        n = int(h.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ApiError(413, "request too large")
        if n == 0:
            return {}
        try:
            data = json.loads(h.rfile.read(n))
        except ValueError:
            raise ApiError(400, "invalid JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "JSON object expected")
        return data

    def need_str(d: dict, key: str) -> str:
        v = d.get(key)
        if not isinstance(v, str):
            raise ApiError(400, f"'{key}' (string) is required")
        return v

    # (method, regex, handler(h, match, query) -> (status, payload))
    R = []

    def route(method: str, pattern: str):
        def deco(fn):
            R.append((method, re.compile(f"^{pattern}$"), fn))
            return fn
        return deco

    @route("GET", r"/api/health")
    def health(h, m, q):
        return 200, {"status": "ok", "llm": bool(c.llm and c.llm.enabled), "webhook": bool(settings.webhook_url)}

    @route("GET", r"/api/patients")
    def patients(h, m, q):
        return 200, c.list_patients()

    @route("POST", r"/api/patients")
    def new_patient(h, m, q):
        d = body_of(h)
        return 201, c.create_patient(need_str(d, "name"), d.get("language", "en"),
                                     d.get("caregiver_name", ""), d.get("caregiver_contact", ""))

    @route("PUT", r"/api/patients/(\d+)")
    def edit_patient(h, m, q):
        return 200, c.update_patient(int(m[1]), **body_of(h))

    @route("GET", r"/api/patients/(\d+)/today")
    def today(h, m, q):
        return 200, c.today(int(m[1]))

    @route("GET", r"/api/patients/(\d+)/medications")
    def meds(h, m, q):
        c.get_patient(int(m[1]))
        return 200, c.list_medications(int(m[1]))

    @route("POST", r"/api/patients/(\d+)/medications")
    def add_med(h, m, q):
        d = body_of(h)
        times = d.get("times")
        if not isinstance(times, list):
            raise ApiError(400, "'times' (list of HH:MM) is required")
        gap = d.get("min_gap_hours")
        return 201, c.add_medication(int(m[1]), need_str(d, "name"), times, str(d.get("dose", "")),
                                     str(d.get("instructions", "")), float(gap) if gap not in (None, "") else None)

    @route("DELETE", r"/api/medications/(\d+)")
    def del_med(h, m, q):
        c.remove_medication(int(m[1]))
        return 200, {"ok": True}

    @route("POST", r"/api/patients/(\d+)/talk")
    def talk(h, m, q):
        d = body_of(h)
        text = need_str(d, "text")
        if len(text) > 500:
            raise ApiError(400, "text too long")
        return 200, c.handle_utterance(int(m[1]), text, lang=d.get("lang"))

    @route("POST", r"/api/doses/(\d+)/take")
    def take(h, m, q):
        r = c.take(int(m[1]), force=bool(body_of(h).get("force")))
        return (200 if r["ok"] else 409), r

    @route("POST", r"/api/doses/(\d+)/skip")
    def skip(h, m, q):
        r = c.skip(int(m[1]))
        return (200 if r["ok"] else 409), r

    @route("POST", r"/api/doses/(\d+)/snooze")
    def snooze(h, m, q):
        return 200, c.snooze(int(m[1]), int(body_of(h).get("minutes", 15)))

    @route("GET", r"/api/patients/(\d+)/insights")
    def insights(h, m, q):
        return 200, c.insights(int(m[1]), int((q.get("days") or ["14"])[0]))

    @route("GET", r"/api/patients/(\d+)/alerts")
    def alerts(h, m, q):
        return 200, c.alerts(int(m[1]))

    @route("POST", r"/api/alerts/(\d+)/ack")
    def ack(h, m, q):
        c.ack_alert(int(m[1]))
        return 200, {"ok": True}

    class Handler(BaseHTTPRequestHandler):
        server_version = "Sanjeevani/1.0"

        def log_message(self, fmt, *args):  # route access logs through logging
            log.info("%s %s", self.address_string(), fmt % args)

        def _send(self, status: int, payload, ctype: str = "application/json") -> None:
            raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(raw)

        def _authorized(self) -> bool:
            if not settings.api_token:
                return True
            supplied = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            return hmac.compare_digest(supplied, settings.api_token)

        def _dispatch(self, method: str) -> None:
            url = urlparse(self.path)
            try:
                if method == "GET" and url.path in ("/", "/index.html"):
                    return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                if not url.path.startswith("/api/"):
                    raise ApiError(404, "not found")
                if url.path != "/api/health" and not self._authorized():
                    raise ApiError(401, "missing or invalid token")
                for meth, rx, fn in R:
                    m = rx.match(url.path)
                    if m and meth == method:
                        status, payload = fn(self, m, parse_qs(url.query))
                        return self._send(status, payload)
                raise ApiError(404, "not found")
            except ApiError as e:
                self._send(e.status, {"error": e.message})
            except LookupError as e:
                self._send(404, {"error": str(e)})
            except (ValueError, TypeError) as e:
                self._send(400, {"error": str(e)})
            except Exception:  # never leak internals
                log.exception("unhandled error")
                self._send(500, {"error": "internal error"})

        def do_GET(self): self._dispatch("GET")
        def do_POST(self): self._dispatch("POST")
        def do_PUT(self): self._dispatch("PUT")
        def do_DELETE(self): self._dispatch("DELETE")

    return Handler


class Ticker(threading.Thread):
    """Runs the escalation heartbeat in the background."""

    def __init__(self, companion: Companion, seconds: int) -> None:
        super().__init__(daemon=True, name="sanjeevani-ticker")
        self.companion, self.seconds, self._stop_evt = companion, seconds, threading.Event()

    def run(self) -> None:
        while not self._stop_evt.is_set():
            try:
                self.companion.tick()
            except Exception:
                log.exception("tick failed")
            self._stop_evt.wait(self.seconds)

    def stop(self) -> None:
        self._stop_evt.set()


def create_server(companion: Companion, settings: Settings) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((settings.host, settings.port), make_handler(companion, settings))
