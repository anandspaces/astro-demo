#!/usr/bin/env python
"""Tiny stdlib HTTP server exposing the StarSage pipeline for the web UI.

No extra dependencies. Serves the static frontend from web/ and provides:
    GET  /api/provider                      -> current provider + key status
    POST /api/signup   {name,dob,tob,pob,tz,lat?,lon?}  -> {user_id, summary}
    GET  /api/chart?user=<id>               -> full natal chart JSON
    POST /api/chat     {user_id,session,message,provider?} -> {response}

Run:  python server.py   (then open http://localhost:8765)
"""
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

import main  # noqa: E402  (loads .env, sets paths)
from astro import build_natal_chart  # noqa: E402
from db import store  # noqa: E402
from pipeline import llm  # noqa: E402
from pipeline.router import route  # noqa: E402
from pipeline.stream import stream_route  # noqa: E402

WEB_DIR = os.path.join(ROOT, "web")
PORT = int(os.environ.get("STARSAGE_PORT", "8765"))
_provider_lock = threading.Lock()   # serialise provider-env swaps during chat


def _summary(chart):
    d = chart["dashas"]
    return {
        "lagna": chart["lagna"]["sign"],
        "lagna_degree": chart["lagna"]["degree"],
        "moon": chart["planets"]["Moon"]["sign"],
        "dasha": f"{d['current_MD']['planet']} MD → {d['current_AD']['planet']} AD → {d['current_PD']['planet']} PD",
        "yogas": [y["name"] for y in chart["yogas"]],
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=WEB_DIR, **k)

    def log_message(self, *a):
        pass  # quiet

    def _send(self, code, obj):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    # -- routing ----------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/provider":
            return self._send(200, {
                "provider": llm.resolve_provider(),
                "quality": llm.model_for("quality"),
                "fast": llm.model_for("fast"),
                "keys": {p: bool(llm._key_for(p)) for p in ("claude", "gpt", "gemini")},
            })
        if path == "/api/chart":
            qs = parse_qs(urlparse(self.path).query)
            uid = (qs.get("user") or [""])[0]
            chart = store.get_user_chart(uid)
            return self._send(200 if chart else 404, chart or {"error": "no chart for user"})
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/signup":
                return self._signup()
            if path == "/api/chat":
                return self._chat()
            if path == "/api/chat/stream":
                return self._chat_stream()
        except Exception as e:
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})
        return self._send(404, {"error": "unknown endpoint"})

    def _signup(self):
        b = self._body()
        store.init_db()
        lat = float(b["lat"]) if b.get("lat") else None
        lon = float(b["lon"]) if b.get("lon") else None
        uid = store.create_user(b["name"], b["dob"], b["tob"], b["pob"], b["tz"], lat, lon)
        meta = {"name": b["name"], "dob": b["dob"], "tob": b["tob"], "pob": b["pob"], "timezone": b["tz"]}
        if lat is not None:
            meta["lat"], meta["lon"] = lat, lon
        chart = build_natal_chart(meta, target=datetime.utcnow())
        store.save_chart(uid, chart)
        return self._send(200, {"user_id": uid, "summary": _summary(chart)})

    def _chat(self):
        b = self._body()
        provider = (b.get("provider") or "").strip().lower()
        with _provider_lock:
            prev = os.environ.get("STARSAGE_PROVIDER")
            if provider:
                os.environ["STARSAGE_PROVIDER"] = provider
            try:
                resp = route(b["user_id"], b.get("session", "web"), b["message"])
                used = llm.resolve_provider()
            finally:
                if provider:
                    if prev is None:
                        os.environ.pop("STARSAGE_PROVIDER", None)
                    else:
                        os.environ["STARSAGE_PROVIDER"] = prev
        return self._send(200, {"response": resp, "provider": used})

    def _chat_stream(self):
        """Server-Sent Events: streams stage + token events as the reading is written."""
        b = self._body()
        provider = (b.get("provider") or "").strip().lower()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def emit(kind, data):
            try:
                self.wfile.write(f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                raise

        with _provider_lock:
            prev = os.environ.get("STARSAGE_PROVIDER")
            if provider:
                os.environ["STARSAGE_PROVIDER"] = provider
            try:
                stream_route(b["user_id"], b.get("session", "web"), b["message"], emit)
            except (BrokenPipeError, ConnectionResetError):
                pass  # client navigated away
            except Exception as e:
                try:
                    emit("error", {"error": f"{type(e).__name__}: {e}"})
                except Exception:
                    pass
            finally:
                if provider:
                    if prev is None:
                        os.environ.pop("STARSAGE_PROVIDER", None)
                    else:
                        os.environ["STARSAGE_PROVIDER"] = prev


if __name__ == "__main__":
    store.init_db()
    print(f"StarSage web UI  →  http://localhost:{PORT}")
    print(f"Default provider: {llm.resolve_provider()} "
          f"(keys: {', '.join(p for p in ('claude','gpt','gemini') if llm._key_for(p)) or 'none — mock mode'})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
