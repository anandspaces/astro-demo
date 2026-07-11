#!/usr/bin/env python
"""Test all configured LLM provider APIs, then run a full pipeline turn.

Usage:
    python scripts/test_apis.py            # test every provider that has a key
    python scripts/test_apis.py claude     # test one provider only

For each provider with a key it makes a real minimal call on both tiers
(quality + fast), reporting latency and an output snippet. Then it runs one
end-to-end StarSage turn (signup -> chart -> chat) through the configured provider.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

# Load .env the same way the CLI does.
import main  # noqa: E402  (runs load_dotenv())
from pipeline import llm  # noqa: E402

PROVIDERS = ["claude", "gpt", "gemini"]


def _snippet(text, n=90):
    text = " ".join((text or "").split())
    return text[:n] + ("…" if len(text) > n else "")


def test_provider(provider):
    key = llm._key_for(provider)
    if not key:
        print(f"  {provider:7} — no key set, skipped")
        return None
    prev = os.environ.get("STARSAGE_PROVIDER")
    os.environ["STARSAGE_PROVIDER"] = provider
    ok = True
    try:
        for tier in ("fast", "quality"):
            model = llm.model_for(tier)
            t0 = time.time()
            try:
                out = llm.call_llm(
                    tier,
                    system="You are a terse test probe. Reply with a single short sentence.",
                    user="Say 'StarSage API OK' and name your model family.",
                    temp=0.2,
                    max_tokens=40,
                )
                dt = time.time() - t0
                print(f"  {provider:7} {tier:7} [{model}]  {dt:4.1f}s  ✅  {_snippet(out)}")
            except Exception as e:
                ok = False
                print(f"  {provider:7} {tier:7} [{model}]  ❌  {type(e).__name__}: {_snippet(str(e), 140)}")
    finally:
        if prev is None:
            os.environ.pop("STARSAGE_PROVIDER", None)
        else:
            os.environ["STARSAGE_PROVIDER"] = prev
    return ok


def end_to_end():
    """One real StarSage reading through the configured provider."""
    from datetime import datetime

    from astro import build_natal_chart
    from db import store
    from pipeline.router import route

    store.DB_PATH = os.path.join(ROOT, "scripts", "_apitest.db")
    if os.path.exists(store.DB_PATH):
        os.remove(store.DB_PATH)
    store.init_db()

    provider = llm.resolve_provider()
    print(f"\n=== END-TO-END pipeline turn  (provider: {provider}, quality={llm.model_for('quality')}) ===")
    meta = {"name": "Asha", "dob": "1992-06-20", "tob": "14:15",
            "pob": "Mumbai, India", "timezone": "Asia/Kolkata"}
    uid = store.create_user(meta["name"], meta["dob"], meta["tob"], meta["pob"], meta["timezone"])
    chart = build_natal_chart(meta, target=datetime(2026, 7, 9))
    store.save_chart(uid, chart)
    print(f"chart: Lagna {chart['lagna']['sign']} | Moon {chart['planets']['Moon']['sign']} "
          f"| MD {chart['dashas']['current_MD']['planet']} | yogas {[y['name'] for y in chart['yogas']][:3]}")

    for msg in ["When will my career take off?", "yes tell me more"]:
        print(f"\nyou > {msg}")
        t0 = time.time()
        resp = route(uid, "apitest", msg)
        print(f"StarSage ({time.time()-t0:.1f}s) >\n{resp}")

    os.remove(store.DB_PATH)


def main_():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    targets = [only] if only else PROVIDERS
    print("=== PROVIDER API PROBES ===")
    results = {}
    for p in targets:
        results[p] = test_provider(p)

    tested = {p: r for p, r in results.items() if r is not None}
    if tested:
        end_to_end()

    print("\n=== SUMMARY ===")
    for p in PROVIDERS:
        r = results.get(p)
        state = "skipped (no key)" if r is None else ("all OK ✅" if r else "FAILURES ❌")
        print(f"  {p:7} {state}")


if __name__ == "__main__":
    main_()
