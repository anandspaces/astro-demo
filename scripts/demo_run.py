#!/usr/bin/env python
"""Run the live pipeline for several distinct users and emit a Markdown samples
section (real chart data + real LLM readings) for the handover doc.

Usage: STARSAGE_PROVIDER=gemini python scripts/demo_run.py > samples.md
"""
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

import main  # noqa: E402  (loads .env)
from astro import build_natal_chart  # noqa: E402
from db import store  # noqa: E402
from pipeline import llm  # noqa: E402
from pipeline.router import route  # noqa: E402

TARGET = datetime(2026, 7, 9)

USERS = [
    {"meta": {"name": "Rohan", "dob": "1988-11-05", "tob": "21:40", "pob": "Delhi, India", "timezone": "Asia/Kolkata"},
     "turns": [("timing", "Will I change jobs, and when?"), ("affirmation", "yes, tell me more")]},
    {"meta": {"name": "Meera", "dob": "1995-03-22", "tob": "06:10", "pob": "Bengaluru, India", "timezone": "Asia/Kolkata"},
     "turns": [("relationship", "What do the planets say about my marriage prospects?")]},
    {"meta": {"name": "Asha", "dob": "1992-06-20", "tob": "14:15", "pob": "Mumbai, India", "timezone": "Asia/Kolkata"},
     "turns": [("forecast", "How will my year ahead look?")]},
]


def chart_line(c):
    d = c["dashas"]
    return (f"Lagna **{c['lagna']['sign']}** ({c['lagna']['degree']}°) · "
            f"Moon **{c['planets']['Moon']['sign']}** · "
            f"Dasha **{d['current_MD']['planet']} MD → {d['current_AD']['planet']} AD → {d['current_PD']['planet']} PD** · "
            f"Karakas: AK {c['special_factors']['atmakaraka']}, AmK {c['special_factors']['amatyakaraka']} · "
            f"Yogas: {', '.join(y['name'] for y in c['yogas']) or 'none'}")


def main_():
    store.DB_PATH = os.path.join(ROOT, "scripts", "_samples.db")
    if os.path.exists(store.DB_PATH):
        os.remove(store.DB_PATH)
    store.init_db()

    print(f"_Provider: **{llm.resolve_provider()}** (quality `{llm.model_for('quality')}`, "
          f"fast `{llm.model_for('fast')}`). Charts computed for reference date {TARGET.date()}._\n")

    for i, u in enumerate(USERS, 1):
        m = u["meta"]
        uid = store.create_user(m["name"], m["dob"], m["tob"], m["pob"], m["timezone"])
        chart = build_natal_chart(m, target=TARGET)
        store.save_chart(uid, chart)
        print(f"## Sample {i} — {m['name']}")
        print(f"**Birth:** {m['dob']} {m['tob']}, {m['pob']}  ")
        print(f"**Computed chart (deterministic):** {chart_line(chart)}\n")
        for kind, msg in u["turns"]:
            t0 = time.time()
            resp = route(uid, f"s{i}", msg)
            dt = time.time() - t0
            print(f"**Q ({kind}, {dt:.0f}s):** {msg}\n")
            print(f"**StarSage:**\n\n{resp}\n")
        print("---\n")

    os.remove(store.DB_PATH)


if __name__ == "__main__":
    main_()
