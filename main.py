#!/usr/bin/env python
"""StarSage CLI — signup, build chart, and chat through the full pipeline.

Usage:
    python main.py init
    python main.py signup --name "X" --dob 1990-01-15 --tob 08:30 \
        --pob "Delhi, India" --tz Asia/Kolkata [--lat 28.61 --lon 77.20]
    python main.py chart  --user <user_id>
    python main.py chat   --user <user_id> [--session s1] [--message "..."]

Provider switch (LLM): set STARSAGE_PROVIDER=claude|gpt|gemini (default: auto/mock)
and the matching key (ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY).
"""
import argparse
import json
import os
import sys
from datetime import datetime

# Make both the project root (for `db`) and src (for `astro`, `pipeline`) importable.
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))


def load_dotenv(path=None):
    """Minimal .env loader (zero dependency). Existing env vars win; must run
    before the pipeline reads them. Strips inline `# comments` on unquoted
    values so a leftover template comment can't corrupt an API key."""
    import re
    path = path or os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, raw = line.partition("=")
            key = key.strip()
            if raw.lstrip()[:1] in ('"', "'"):        # quoted: keep inner verbatim
                q = raw.lstrip()[0]
                inner = raw.lstrip()[1:]
                val = inner[:inner.index(q)] if q in inner else inner
            else:                                     # unquoted: split off inline comment,
                val = re.split(r"\s#", raw, maxsplit=1)[0].strip()  # then strip (blank stays blank)
            if key and val and key not in os.environ:
                os.environ[key] = val


load_dotenv()

from astro import build_natal_chart          # noqa: E402
from db import store                          # noqa: E402
from pipeline import llm                       # noqa: E402
from pipeline.router import route              # noqa: E402


def cmd_init(_):
    store.init_db()
    print(f"Initialised DB at {store.DB_PATH}")


def cmd_signup(a):
    store.init_db()
    uid = store.create_user(a.name, a.dob, a.tob, a.pob, a.tz, a.lat, a.lon)
    meta = {"name": a.name, "dob": a.dob, "tob": a.tob, "pob": a.pob, "timezone": a.tz}
    if a.lat is not None:
        meta["lat"], meta["lon"] = a.lat, a.lon
    chart = build_natal_chart(meta, target=datetime.utcnow())
    store.save_chart(uid, chart)
    print(f"Created user {uid}")
    print(f"  Lagna: {chart['lagna']['sign']} | Moon: {chart['planets']['Moon']['sign']} "
          f"| MD: {chart['dashas']['current_MD']['planet']}")
    print(f"  Yogas: {[y['name'] for y in chart['yogas']]}")


def cmd_chart(a):
    chart = store.get_user_chart(a.user)
    if not chart:
        print("No chart for that user.")
        return
    print(json.dumps(chart, indent=2, default=str))


def cmd_chat(a):
    store.init_db()
    provider = llm.resolve_provider()
    print(f"[provider: {provider} | quality={llm.model_for('quality')} fast={llm.model_for('fast')}]")
    if a.message:
        print("\n" + route(a.user, a.session, a.message))
        return
    print("Chat with StarSage (empty line to quit).")
    while True:
        try:
            msg = input("\nyou > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not msg:
            break
        print("\nStarSage >", route(a.user, a.session, msg))


def main():
    p = argparse.ArgumentParser(description="StarSage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(fn=cmd_init)

    s = sub.add_parser("signup")
    s.add_argument("--name", required=True)
    s.add_argument("--dob", required=True)
    s.add_argument("--tob", required=True)
    s.add_argument("--pob", required=True)
    s.add_argument("--tz", required=True)
    s.add_argument("--lat", type=float, default=None)
    s.add_argument("--lon", type=float, default=None)
    s.set_defaults(fn=cmd_signup)

    c = sub.add_parser("chart")
    c.add_argument("--user", required=True)
    c.set_defaults(fn=cmd_chart)

    ch = sub.add_parser("chat")
    ch.add_argument("--user", required=True)
    ch.add_argument("--session", default="default")
    ch.add_argument("--message", default=None)
    ch.set_defaults(fn=cmd_chat)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
