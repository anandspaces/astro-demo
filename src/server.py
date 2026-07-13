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

import main  # noqa: E402  (loads .env, sets paths, configures logging)
import logging  # noqa: E402
import keystore  # noqa: E402
from logging_setup import setup_logging  # noqa: E402

log = logging.getLogger("starsage.server")
from astro import build_natal_chart  # noqa: E402
from db import store  # noqa: E402
from pipeline import llm  # noqa: E402
from pipeline import prompts as prompts_mod  # noqa: E402
from pipeline.router import route  # noqa: E402
from pipeline.stream import stream_route  # noqa: E402

WEB_DIR = os.path.join(os.path.dirname(ROOT), "web")
PORT = int(os.environ.get("STARSAGE_PORT", "8765"))
_provider_lock = threading.Lock()   # serialise provider/key-env swaps during chat

PROVIDERS = ("claude", "gpt", "gemini")

# provider -> (encrypted-key column, key env var, chosen-model column)
_KEY_MAP = {
    "claude": ("claude_key_enc", "ANTHROPIC_API_KEY", "claude_model"),
    "gpt": ("gpt_key_enc", "OPENAI_API_KEY", "gpt_model"),
    "gemini": ("gemini_key_enc", "GEMINI_API_KEY", "gemini_model"),
}

# Curated fallback when a provider's key isn't set yet (so no live fetch is possible).
_FALLBACK_MODELS = {
    "claude": ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
    "gpt": ["gpt-4o", "gpt-4o-mini", "o4-mini"],
    "gemini": ["gemini-3.1-pro-preview", "gemini-3.5-flash", "gemini-2.5-pro", "gemini-2.5-flash"],
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


def _prompts_view():
    """Every editable pipeline prompt: its effective text (override or default),
    the default (for a reset/diff), and whether it's currently overridden."""
    overrides = store.get_all_prompt_overrides()
    out = []
    for name, meta in prompts_mod.PROMPT_META.items():
        out.append({
            "name": name,
            "label": meta["label"],
            "note": meta["note"],
            "content": prompts_mod.get_prompt(name),          # effective (override or default)
            "default": prompts_mod.default_prompt(name),
            "overridden": name in overrides,
        })
    return {"prompts": out}


def _settings_view():
    """Provider, which keys are set (masked), and the chosen/default model per
    provider. Never returns raw keys."""
    st = store.get_settings()
    keys, models = {}, {}
    for prov, (enc_col, _env, model_col) in _KEY_MAP.items():
        plain = keystore.decrypt_secret(st.get(enc_col)) if st.get(enc_col) else None
        keys[prov] = {"set": bool(plain), "hint": keystore.mask_secret(plain or "")}
        models[prov] = {"chosen": st.get(model_col) or "", "default": llm.MODELS[prov]["quality"]}
    return {
        "provider": st.get("provider") or "",
        "providers": list(PROVIDERS),
        "keys": keys,
        "models": models,
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

        for prov, (enc_col, env, _model_col) in _KEY_MAP.items():
            plain = keystore.decrypt_secret(st.get(enc_col)) if st.get(enc_col) else None
            if plain:
                setenv(env, plain)
        prov = (self._override or st.get("provider") or "").strip().lower()
        if prov:
            setenv("STARSAGE_PROVIDER", prov)
        # Apply the chosen model for the active provider to the reading (quality) tier.
        if prov in _KEY_MAP:
            chosen = st.get(_KEY_MAP[prov][2])
            if chosen:
                setenv(f"STARSAGE_{prov.upper()}_QUALITY", chosen)
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

    def end_headers(self):
        # Never cache API responses or console assets, so a redeploy is picked up
        # immediately instead of serving a stale UI from the browser cache.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

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
        if path == "/api/prompts":
            return self._send(200, _prompts_view())
        if path == "/api/models":
            return self._list_models()
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
        path = urlparse(self.path).path
        try:
            if path == "/api/settings":
                return self._put_settings()
            if path == "/api/prompts":
                return self._put_prompt()
        except Exception as e:
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})
        return self._send(404, {"error": "unknown endpoint"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/settings":       # POST accepted as alias for PUT
                return self._put_settings()
            if path == "/api/prompts":        # POST accepted as alias for PUT
                return self._put_prompt()
            if path == "/api/prompts/reset":
                return self._reset_prompt()
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
            if provider and provider not in PROVIDERS:
                return self._send(400, {"error": f"unknown provider: {provider}"})
        # keys: {provider: "raw-key" to set, "" or null to clear}
        key_enc = {}
        for prov, val in (b.get("keys") or {}).items():
            if prov not in _KEY_MAP:
                continue
            key_enc[prov] = None if (val is None or val == "") else keystore.encrypt_secret(val.strip())
        # models: {provider: "model-id" or "" to reset to default}
        models = {}
        for prov, val in (b.get("models") or {}).items():
            if prov not in _KEY_MAP:
                continue
            models[prov] = (val or "").strip() or None
        store.save_settings(provider=provider, key_enc_by_provider=key_enc, model_by_provider=models)
        return self._send(200, _settings_view())

    # -- prompts ----------------------------------------------------------
    def _put_prompt(self):
        """Save an override for one pipeline prompt. Rejects unknown names and, for
        the preamble, an override that drops a required {placeholder}."""
        b = self._body()
        name = (b.get("name") or "").strip()
        content = b.get("content")
        if name not in prompts_mod.PROMPT_META:
            return self._send(400, {"error": f"unknown prompt: {name}"})
        if not isinstance(content, str) or not content.strip():
            return self._send(400, {"error": "content must be a non-empty string"})
        if name == "preamble" and not prompts_mod._valid_preamble(content):
            missing = [f for f in prompts_mod._PREAMBLE_FIELDS if "{" + f + "}" not in content]
            return self._send(400, {"error": f"preamble is missing required placeholders: {missing}"})
        store.save_prompt_override(name, content)
        return self._send(200, _prompts_view())

    def _reset_prompt(self):
        """Delete an override so the prompt reverts to its hardcoded default."""
        b = self._body()
        name = (b.get("name") or "").strip()
        if name not in prompts_mod.PROMPT_META:
            return self._send(400, {"error": f"unknown prompt: {name}"})
        store.delete_prompt_override(name)
        return self._send(200, _prompts_view())

    def _list_models(self):
        """Live model ids from the provider's official API, using the stored key;
        falls back to a curated list if no key is set or the fetch fails."""
        qs = parse_qs(urlparse(self.path).query)
        provider = (qs.get("provider") or [""])[0].strip().lower()
        if provider not in _KEY_MAP:
            return self._send(400, {"error": f"unknown provider: {provider}"})
        enc_col = _KEY_MAP[provider][0]
        key = keystore.decrypt_secret(store.get_settings().get(enc_col) or "") if store.get_settings().get(enc_col) else None
        if not key:
            return self._send(200, {"provider": provider, "models": _FALLBACK_MODELS[provider],
                                    "source": "fallback", "note": "add and save this key to load the live list"})
        try:
            models = llm.list_models(provider, key)
            if models:
                return self._send(200, {"provider": provider, "models": models, "source": "live"})
            return self._send(200, {"provider": provider, "models": _FALLBACK_MODELS[provider], "source": "fallback"})
        except Exception as e:
            return self._send(200, {"provider": provider, "models": _FALLBACK_MODELS[provider],
                                    "source": "fallback", "error": f"{type(e).__name__}: {e}"})

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
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()   # Cache-Control: no-store added by end_headers override

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
                log.error("chat/stream failed: %s: %s", type(e).__name__, e, exc_info=True)
                try:
                    emit("error", {"error": f"{type(e).__name__}: {e}"})
                except Exception:
                    pass


if __name__ == "__main__":
    setup_logging()   # idempotent; main import already configured it, this is explicit
    store.init_db()
    print(f"StarSage web UI  →  http://localhost:{PORT}")
    print(f"DB backend: {store.backend_name()} → {store.target()}")
    print(f"Default provider: {llm.resolve_provider()}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
