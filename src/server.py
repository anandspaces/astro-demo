#!/usr/bin/env python
"""Tiny stdlib HTTP server exposing the StarSage pipeline for the web UI.

No extra dependencies. Serves the static frontend from web/ and provides:
    GET  /api/provider                      -> effective provider + key status
    GET  /api/settings                      -> selected model + which keys are set (masked)
    PUT  /api/settings {provider?, keys?}    -> switch model / store an API key (encrypted)
    POST /api/signup   {name,dob,tob,pob,tz,lat?,lon?}  -> {user_id, summary}
    GET  /api/chart?user=<id>               -> full natal chart JSON
    POST /api/chat     {user_id,session,message,provider?} -> {response}

The chosen provider + API key are stored (encrypted) in the DB via /api/settings,
so they survive a refresh; the chat call applies them to the pipeline per request.
(Authentication is intentionally not here yet — settings are a single shared row.)

Run:  python src/server.py   (then open http://localhost:8765)
"""
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = ROOT
sys.path.insert(0, SRC)

import main  # noqa: E402  (loads .env, sets paths)
import keystore  # noqa: E402
from astro import build_natal_chart  # noqa: E402
from db import store  # noqa: E402
from pipeline import llm  # noqa: E402
from pipeline.router import route  # noqa: E402
from pipeline.stream import stream_route  # noqa: E402

WEB_DIR = os.path.join(os.path.dirname(ROOT), "web")
PORT = int(os.environ.get("STARSAGE_PORT", "8765"))
_provider_lock = threading.Lock()   # serialise provider/key-env swaps during chat

# provider -> (settings column holding the encrypted key, env var the SDK reads)
_KEY_MAP = {
    "claude": ("claude_key_enc", "ANTHROPIC_API_KEY"),
    "gpt": ("gpt_key_enc", "OPENAI_API_KEY"),
    "gemini": ("gemini_key_enc", "GEMINI_API_KEY"),
}


def _summary(chart):
    d = chart["dashas"]
    return {
        "lagna": chart["lagna"]["sign"],
        "lagna_degree": chart["lagna"]["degree"],
        "moon": chart["planets"]["Moon"]["sign"],
        "dasha": f"{d['current_MD']['planet']} MD → {d['current_AD']['planet']} AD → {d['current_PD']['planet']} PD",
        "yogas": [y["name"] for y in chart["yogas"]],
    }


def _settings_view():
    """Provider + which keys are set (masked). Never returns raw keys."""
    st = store.get_settings()
    keys = {}
    for prov, (enc_col, _env) in _KEY_MAP.items():
        plain = keystore.decrypt_secret(st.get(enc_col)) if st.get(enc_col) else None
        keys[prov] = {"set": bool(plain), "hint": keystore.mask_secret(plain or "")}
    return {
        "provider": st.get("provider") or "",
        "keys": keys,
        "providers": ["claude", "gpt", "gemini", "mock"],
        "models": {p: {"quality": llm.MODELS[p]["quality"], "fast": llm.MODELS[p]["fast"]}
                   for p in ("claude", "gpt", "gemini")},
    }


class _LLMEnv:
    """Context manager: apply the stored provider + decrypted keys to the process
    env for the duration of a call, serialised by a lock, then restore. Keeps
    pipeline/llm.py unchanged (it reads keys/provider from env)."""

    def __init__(self, override_provider=None):
        self._override = override_provider

    def __enter__(self):
        _provider_lock.acquire()
        self._saved = {}
        st = store.get_settings()

        def setenv(k, v):
            self._saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

        for prov, (enc_col, env) in _KEY_MAP.items():
            plain = keystore.decrypt_secret(st.get(enc_col)) if st.get(enc_col) else None
            if plain:
                setenv(env, plain)
        prov = (self._override or st.get("provider") or "").strip().lower()
        if prov:
            setenv("STARSAGE_PROVIDER", prov)
        return self

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _provider_lock.release()
        return False


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
        if path == "/api/settings":
            return self._send(200, _settings_view())
        if path == "/api/provider":
            with _LLMEnv():
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

    def do_PUT(self):
        if urlparse(self.path).path == "/api/settings":
            try:
                return self._put_settings()
            except Exception as e:
                return self._send(500, {"error": f"{type(e).__name__}: {e}"})
        return self._send(404, {"error": "unknown endpoint"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/settings":       # POST accepted as alias for PUT
                return self._put_settings()
            if path == "/api/signup":
                return self._signup()
            if path == "/api/chat":
                return self._chat()
            if path == "/api/chat/stream":
                return self._chat_stream()
        except Exception as e:
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})
        return self._send(404, {"error": "unknown endpoint"})

    # -- settings ---------------------------------------------------------
    def _put_settings(self):
        b = self._body()
        provider = b.get("provider")
        if provider is not None:
            provider = provider.strip().lower()
            if provider and provider not in ("claude", "gpt", "gemini", "mock"):
                return self._send(400, {"error": f"unknown provider: {provider}"})
        # keys: {provider: "raw-key" to set, "" or null to clear}
        key_enc = {}
        for prov, val in (b.get("keys") or {}).items():
            if prov not in _KEY_MAP:
                continue
            key_enc[prov] = None if (val is None or val == "") else keystore.encrypt_secret(val.strip())
        store.save_settings(provider=provider, key_enc_by_provider=key_enc)
        return self._send(200, _settings_view())

    # -- chart / chat -----------------------------------------------------
    def _signup(self):
        b = self._body()
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
        override = (b.get("provider") or "").strip().lower() or None
        with _LLMEnv(override):
            resp = route(b["user_id"], b.get("session", "web"), b["message"])
            used = llm.resolve_provider()
        return self._send(200, {"response": resp, "provider": used})

    def _chat_stream(self):
        """Server-Sent Events: streams stage + token events as the reading is written."""
        b = self._body()
        override = (b.get("provider") or "").strip().lower() or None
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

        with _LLMEnv(override):
            try:
                stream_route(b["user_id"], b.get("session", "web"), b["message"], emit)
            except (BrokenPipeError, ConnectionResetError):
                pass  # client navigated away
            except Exception as e:
                try:
                    emit("error", {"error": f"{type(e).__name__}: {e}"})
                except Exception:
                    pass


if __name__ == "__main__":
    store.init_db()
    print(f"StarSage web UI  →  http://localhost:{PORT}")
    print(f"DB backend: {store.backend_name()} → {store.target()}")
    print(f"Default provider: {llm.resolve_provider()}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
