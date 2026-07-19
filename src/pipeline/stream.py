"""Streaming router for the web UI. Emits pipeline-stage + token events.

SYNCHRONOUS CRITIC (priority fix, 2026-07 — reverted from the Part 16 async model).
The main reading path now runs the full quality gate BEFORE any text reaches the
user:  Planner → Generator (full draft, not streamed) → Critic → maybe one rewrite
→ only then stream the vetted text token-by-token. This costs the user some
time-to-first-token, but guarantees they never see a broken/truncated draft that
the Critic would have caught (the old async path streamed the draft first and
critiqued it after the user had already read it).

DO NOT revert to the async "stream-then-critique" model until response quality is
stable. When reverting, restore stream_generator() here and drop the _emit_text
replay below.

on_event(kind, data): kind in {"meta","stage","token","done","error"}.
  stage payloads: {"stage": "classifying|planning|writing|reviewing", "detail": str}
"""
import logging
from datetime import datetime

log = logging.getLogger("starsage.stream")

from astro.transits import calculate_timing_confidence, get_transits_for_dasha_window
from db import store
from db.ledger import get_or_create_ledger, planner_view, update_ledger

from . import critic as critic_mod
from . import generator as gen_mod
from . import planner as planner_mod
from . import llm
from .chart_map import get_chart_slice, merge_chart_slices
from .classify import classify_domain, classify_query_type
from . import prompts


def _attach_future_transits(planner_json, chart):
    lagna_sign = chart["lagna"]["sign"]
    moon_sign = chart["planets"]["Moon"]["sign"]
    future = {}
    for label, start, end in planner_mod.normalise_windows(planner_json):
        if not (start and end):
            continue
        try:
            s, e = datetime.strptime(start, "%Y-%m-%d"), datetime.strptime(end, "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        future[label] = get_transits_for_dasha_window(s, e, lagna_sign, moon_sign)
    if future:
        planner_json["future_transits"] = future
        planner_json["timing_confidence"] = calculate_timing_confidence(
            True, True, planner_json.get("divisional_chart") is not None)
    return planner_json


def _emit_text(text, on_event):
    """Replay already-finalised text to the client as token events, so the UI keeps
    its streaming animation even though the draft was generated synchronously."""
    words = text.split(" ")
    for i in range(0, len(words), 3):
        on_event("token", {"text": " ".join(words[i:i + 3]) + " "})


def _persist_session_state(session_id, planner_json):
    """Write last_mechanism/domain/axis. A silent failure here corrupts rotation on
    every subsequent turn, so failures are caught and logged loudly (priority fix)."""
    try:
        ok = store.update_session_state(session_id, planner_json)
        if not ok:
            log.error("session-state write no-op for session=%s (row missing?); "
                      "last_mechanism NOT persisted — mechanism rotation will break", session_id)
    except Exception as e:
        log.error("session-state write FAILED for session=%s: %s: %s",
                  session_id, type(e).__name__, e, exc_info=True)


def _stream_reading(user_id, session_id, message, chart, on_event, *, primary, secondary,
                    query_type, forced_domain=None):
    state = store.get_session_state(session_id)     # read fresh from DB every turn (no cache)
    domain = forced_domain or primary
    ledger = get_or_create_ledger(user_id, domain)
    chart_slice = get_chart_slice(chart, domain)
    if secondary:
        chart_slice = merge_chart_slices(chart_slice, get_chart_slice(chart, secondary))
    history = store.get_recent_history(session_id, limit=6)

    on_event("stage", {"stage": "planning", "detail": "choosing the reading angle"})
    planner_json = planner_mod.run_planner(
        message, chart_slice, planner_view(ledger), state,
        query_type=query_type, primary_domain=domain, secondary_domain=secondary)
    if query_type in ("timing", "mixed", "forecast"):
        planner_json = _attach_future_transits(planner_json, chart)

    on_event("meta", {"domain": domain, "mechanism": planner_json.get("mechanism"),
                      "insight_axis": planner_json.get("insight_axis"),
                      "intent": planner_json.get("intent"),
                      "timing_windows": planner_json.get("timing_windows", [])})

    # SYNCHRONOUS: generate the full draft WITHOUT streaming it to the user yet.
    on_event("stage", {"stage": "writing", "detail": f"{planner_json.get('mechanism')} · {domain}"})
    response = gen_mod.run_generator(message, chart_slice, planner_json, history, rotation=state)

    # Critic runs BEFORE the user sees anything; one same-turn rewrite on failure,
    # and only when the failure is severe enough to be worth a second generation.
    on_event("stage", {"stage": "reviewing", "detail": "grounding & quality check"})
    critic_json = critic_mod.run_critic(response, planner_json, ledger, chart_slice)
    if critic_mod.should_retry(critic_json):
        response = gen_mod.run_generator(message, chart_slice, planner_json, history,
                                         rewrite_instruction=critic_json.get("rewrite_instruction"),
                                         rotation=state)

    # P1.2: persist last_mechanism immediately after generation, BEFORE any text is
    # returned to the user, so the next turn's Planner reads the correct prior mechanism.
    _persist_session_state(session_id, planner_json)

    # Only now stream the vetted text to the client.
    _emit_text(response, on_event)

    update_ledger(user_id, domain, planner_json, critic_json)
    if secondary and not forced_domain:
        update_ledger(user_id, secondary, planner_json, critic_json)
    store.increment_interaction_count(session_id)
    store.save_turn(session_id, user_id, "user", message, domain, query_type=query_type)
    store.save_turn(session_id, user_id, "assistant", response, domain,
                    planner_json.get("mechanism"),
                    insight_axis=planner_json.get("insight_axis"),
                    closing_type=planner_json.get("closing_type"))
    return response, critic_json


def _stream_affirmation(user_id, session_id, message, chart, on_event):
    state = store.get_session_state(session_id)
    domain = state.get("last_domain") or "general"
    from .precheck import last_sentence
    cue = last_sentence(store.get_last_assistant_turn(session_id))
    chart_slice = get_chart_slice(chart, domain)
    history = store.get_recent_history(session_id, limit=6)
    on_event("meta", {"domain": domain, "mechanism": "continuation"})
    on_event("stage", {"stage": "writing", "detail": "continuing the thread"})

    if llm.is_mock():
        planner_json = {"query_type": "affirmation", "domain": domain, "mechanism": "continuation",
                        "insight_axis": "behaviour", "intent": "descriptive", "response_structure": "thematic_structure"}
        text = gen_mod.stream_generator(message, chart_slice, planner_json, history,
                                        lambda d: on_event("token", {"text": d}))
    else:
        user = (f"The user affirmed with: \"{message}\". Address this continuation cue directly and "
                f"immediately: {cue}. Do not reintroduce context. Pick up from where the last response ended.")
        acc = []
        try:
            for delta in llm.stream_llm("quality", prompts.get_prompt("system"), history, user, 0.75, 1100):
                acc.append(delta)
                on_event("token", {"text": delta})
            text = "".join(acc)
        except Exception as e:
            log.error("affirmation stream failed: %s: %s", type(e).__name__, e, exc_info=True)
            on_event("error", {"error": str(e)})
            return
    store.save_turn(session_id, user_id, "user", message, domain)
    store.save_turn(session_id, user_id, "assistant", text, domain)
    store.increment_interaction_count(session_id)


def _stream_synthesis(user_id, session_id, chart, on_event):
    history = store.get_recent_history(session_id, limit=6)
    on_event("meta", {"domain": "synthesis", "mechanism": "cross-domain pattern"})
    on_event("stage", {"stage": "writing", "detail": "synthesising across domains"})
    if llm.is_mock():
        planner_json = {"query_type": "forecast", "domain": "synthesis", "mechanism": "synthesis",
                        "insight_axis": "consequence", "intent": "descriptive", "response_structure": "forecast_structure"}
        chart_slice = get_chart_slice(chart, "forecast")
        text = gen_mod.stream_generator("[synthesis]", chart_slice, planner_json, history,
                                        lambda d: on_event("token", {"text": d}))
    else:
        from .format_chart import format_chart_for_generator
        directive = ("SYNTHESIS MODE. Identify the single most significant structural pattern across "
                     "multiple life domains, grounded in specific planetary combinations, and connect it "
                     "to the current dasha. No question, no hook. End with one declarative statement about 2026.")
        all_ledgers = store.get_all_domain_ledgers(user_id)
        user = f"{directive}\n\nLEDGER:\n{all_ledgers}\n\n{format_chart_for_generator(get_chart_slice(chart,'forecast'))}"
        acc = []
        for delta in llm.stream_llm("quality", prompts.get_prompt("system"), history, user, 0.8, 1000):
            acc.append(delta)
            on_event("token", {"text": delta})
        text = "".join(acc)
    store.save_turn(session_id, user_id, "user", "[synthesis triggered]", "synthesis")
    store.save_turn(session_id, user_id, "assistant", text, "synthesis", "synthesis")
    store.increment_interaction_count(session_id)


def stream_route(user_id, session_id, message, on_event):
    """Route + stream one turn. Emits events via on_event; returns nothing."""
    store.get_or_create_session(session_id, user_id)
    chart = store.get_user_chart(user_id)
    if chart is None:
        on_event("error", {"error": f"No chart for user {user_id}"})
        return

    count = store.get_interaction_count(session_id)
    qt = classify_query_type(message)
    on_event("stage", {"stage": "classifying", "detail": qt})

    try:
        if count > 0 and count % 7 == 0:
            on_event("meta", {"mode": "synthesis"})
            _stream_synthesis(user_id, session_id, chart, on_event)
        elif qt == "affirmation":
            _stream_affirmation(user_id, session_id, message, chart, on_event)
        elif qt == "forecast":
            _stream_reading(user_id, session_id, message, chart, on_event,
                            primary="forecast", secondary=None, query_type="forecast", forced_domain="forecast")
        else:
            domains = classify_domain(message)
            _stream_reading(user_id, session_id, message, chart, on_event,
                            primary=domains[0], secondary=(domains[1] if len(domains) > 1 else None),
                            query_type=qt)
        on_event("done", {"provider": llm.resolve_provider()})
    except Exception as e:
        log.error("stream_route failed (user=%s session=%s): %s: %s",
                  user_id, session_id, type(e).__name__, e, exc_info=True)
        on_event("error", {"error": f"{type(e).__name__}: {e}"})
