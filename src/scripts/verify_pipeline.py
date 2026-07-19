#!/usr/bin/env python
"""End-to-end pipeline verification against a real database, no LLM required.

Runs a multi-turn session through the router and, AFTER EVERY SINGLE TURN, queries
the database directly to confirm the writes actually landed — rather than checking
once at the end, where a dropped write on turn 3 hides behind a good write on turn 8.

Checks, per turn:
  - session_messages gained a user row and an assistant row
  - the assistant row carries mechanism_used / insight_axis / closing_type_used
  - the domain ledger's answered_angles grew by exactly one
  - interaction_count advanced
  - rotation state read back for the next turn matches what was just written

Plus two structural checks that need no turns:
  - the plan preamble is in the SYSTEM message and NOT in the user message
  - a Planner mechanism outside the approved list is rejected for the fallback

Usage (from the repo root, per project convention):
    STARSAGE_PROVIDER=mock PYTHONPATH=src .venv/bin/python -m scripts.verify_pipeline
"""
import os
import sys
from datetime import datetime

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC)

os.environ.setdefault("STARSAGE_PROVIDER", "mock")

import main  # noqa: E402,F401  (loads .env)
from sqlalchemy import select  # noqa: E402

from astro import build_natal_chart  # noqa: E402
from db import store  # noqa: E402
from db.models import SessionMessage  # noqa: E402
from pipeline import generator, llm, planner  # noqa: E402
from pipeline.router import route  # noqa: E402

# The chart from docs/pipeline-fixes-plan.md §0 (verified against a reference app).
# Explicit lat/lon: the engine does no geocoding.
BIRTH = {"name": "VerifyUser", "dob": "1989-03-27", "tob": "07:00",
         "pob": "Rezekne, Latvia", "timezone": "Europe/Riga",
         "lat": 56.51, "lon": 27.33}
TARGET = datetime(2026, 7, 19)

TURNS = [
    "Why does my career keep stalling at the same point?",
    "What is blocking my promotion at work?",
    "How do my colleagues actually see me?",
    "yes, tell me more",
    "Will I get a senior role, and when?",
    "What should I stop doing in my job?",
    "Does my work pattern repeat in my family?",
    "How is my career shaping up overall?",     # 8th turn -> synthesis (count % 7)
]

failures = []


def check(ok, label, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(f"{label}: {detail}")
    return ok


def assistant_rows(session_id):
    with store.Session() as s:
        return s.execute(
            select(SessionMessage.role, SessionMessage.domain, SessionMessage.mechanism_used,
                   SessionMessage.insight_axis, SessionMessage.closing_type_used,
                   SessionMessage.query_type)
            .where(SessionMessage.session_id == session_id, SessionMessage.role == "assistant")
            .order_by(SessionMessage.created_at.asc())
        ).all()


def message_count(session_id):
    with store.Session() as s:
        return len(s.execute(
            select(SessionMessage.id).where(SessionMessage.session_id == session_id)).all())


def structural_checks():
    """The headline fix: the plan must reach the model as a system instruction."""
    print("\n[structural] preamble placement + planner validation")
    chart = build_natal_chart(BIRTH, target=TARGET)
    from pipeline.chart_map import get_chart_slice
    chart_slice = get_chart_slice(chart, "career")
    plan = planner.build_fallback_planner("career", "thematic", {}, chart_slice)
    plan["factors_to_use"] = ["10th lord Jupiter in the 6th"]

    system, user = generator.build_generator_payload(
        "Why does my career stall?", chart_slice, plan,
        rotation={"last_mechanism": "nakshatra", "last_insight_axis": "cost",
                  "last_domain": "career", "last_closing_type": "hook"})

    check("READING PLAN FOR THIS TURN" in system, "preamble is in the system message")
    check("READING PLAN FOR THIS TURN" not in user, "preamble is NOT in the user message")
    check(plan["mechanism"] in system, "mechanism reaches the model", plan["mechanism"])
    check(plan["insight_axis"] in system, "insight axis reaches the model", plan["insight_axis"])
    check(str(plan["closing_type"]) in system, "closing type reaches the model", plan["closing_type"])
    check("10th lord Jupiter in the 6th" in system, "planned factors reach the model")
    check("nakshatra" in system, "previous mechanism reaches the model (rotation)")
    check(user.strip().endswith("Why does my career stall?"), "user message is chart + question only")

    # Mechanism validation (rejects a hallucinated mechanism, keeps a valid one).
    bad = {"mechanism": "vibe_reading", "insight_axis": "behaviour", "domain": "career"}
    good = {"mechanism": "house_lord_placement", "insight_axis": "behaviour", "domain": "career"}
    check(planner.validate_plan(bad, "thematic") is not None,
          "unapproved mechanism rejected", planner.validate_plan(bad, "thematic"))
    check(planner.validate_plan(good, "thematic") is None, "approved mechanism accepted")
    check(planner.validate_plan({**good, "insight_axis": "vibes"}, "thematic") is not None,
          "unapproved insight axis rejected")


def turn_checks():
    print(f"\n[e2e] provider={llm.resolve_provider()} — {len(TURNS)} turns, DB checked after each")
    store.init_db()
    uid = store.create_user(BIRTH["name"], BIRTH["dob"], BIRTH["tob"], BIRTH["pob"], BIRTH["timezone"])
    store.save_chart(uid, build_natal_chart(BIRTH, target=TARGET))
    sid = f"verify-{store.generate_id()[:8]}"

    seen_rotations = []
    prev_angles = {}
    for i, message in enumerate(TURNS, 1):
        before_msgs = message_count(sid)
        route(uid, sid, message)
        print(f"\nturn {i}: {message!r}")

        check(message_count(sid) == before_msgs + 2, "2 message rows written",
              f"{message_count(sid) - before_msgs} written")

        rows = assistant_rows(sid)
        last = rows[-1]
        domain = last.domain
        is_synthesis = domain == "synthesis"
        is_affirmation = last.mechanism_used is None and not is_synthesis

        if not (is_synthesis or is_affirmation):
            check(bool(last.mechanism_used), "mechanism_used persisted", str(last.mechanism_used))
            check(bool(last.insight_axis), "insight_axis persisted", str(last.insight_axis))
            check(bool(last.closing_type_used), "closing_type_used persisted", str(last.closing_type_used))
            seen_rotations.append((last.mechanism_used, last.insight_axis))

            # Ledger: answered_angles must grow by exactly one, every single turn.
            ledger = store.get_ledger_from_db(uid, domain) or {}
            angles = len(ledger.get("answered_angles") or [])
            expected = prev_angles.get(domain, 0) + 1
            check(angles == expected, f"ledger[{domain}].answered_angles grew by 1",
                  f"{prev_angles.get(domain, 0)} -> {angles} (expected {expected})")
            prev_angles[domain] = angles

            # Rotation read back is what we just wrote (next turn's Planner input).
            state = store.get_session_state(sid)
            check(state.get("last_mechanism") == last.mechanism_used,
                  "rotation reads back the mechanism just written",
                  f"{state.get('last_mechanism')} vs {last.mechanism_used}")
            check(state.get("last_closing_type") == last.closing_type_used,
                  "rotation reads back the closing type just written")
        else:
            print(f"  ..   {'synthesis' if is_synthesis else 'affirmation'} turn "
                  f"(no plan rotation expected)")

        check(store.get_interaction_count(sid) == i, "interaction_count advanced",
              f"{store.get_interaction_count(sid)} after {i} turns")

    check(any(r.domain == "synthesis" for r in assistant_rows(sid)),
          "synthesis fired within the session (every 7th interaction)")
    distinct = len(set(seen_rotations))
    check(distinct > 1, "mechanism/axis rotated across turns",
          f"{distinct} distinct (mechanism, axis) pairs in {len(seen_rotations)} planned turns")

    print(f"\nsession {sid}: interaction_count={store.get_interaction_count(sid)}, "
          f"state={ {k: v for k, v in store.get_session_state(sid).items() if k.startswith('last_')} }")


def stream_checks():
    """pipeline/stream.py is a second copy of the pipeline (used by the web UI), so
    every fix has to land there too or the two entry points diverge."""
    print("\n[stream] same invariants through stream_route (web UI path)")
    from pipeline.stream import stream_route

    uid = store.create_user(BIRTH["name"], BIRTH["dob"], BIRTH["tob"], BIRTH["pob"],
                            BIRTH["timezone"], BIRTH["lat"], BIRTH["lon"])
    store.save_chart(uid, build_natal_chart(BIRTH, target=TARGET))
    sid = f"verify-stream-{store.generate_id()[:8]}"

    for i, message in enumerate(TURNS[:3], 1):
        events = []
        stream_route(uid, sid, message, lambda kind, data: events.append((kind, data)))
        kinds = {k for k, _ in events}
        check("error" not in kinds, f"turn {i} streamed without error",
              str([d for k, d in events if k == "error"]))
        check("token" in kinds, f"turn {i} emitted tokens")

        last = assistant_rows(sid)[-1]
        check(bool(last.mechanism_used and last.insight_axis and last.closing_type_used),
              f"turn {i} persisted rotation columns",
              f"{last.mechanism_used}/{last.insight_axis}/{last.closing_type_used}")
        ledger = store.get_ledger_from_db(uid, last.domain) or {}
        check(len(ledger.get("answered_angles") or []) == i,
              f"turn {i} ledger[{last.domain}].answered_angles == {i}",
              str(len(ledger.get("answered_angles") or [])))


def main_():
    structural_checks()
    turn_checks()
    stream_checks()
    print("\n" + "=" * 70)
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main_())
