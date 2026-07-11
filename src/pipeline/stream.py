"""Streaming router for the web UI. Emits pipeline-stage + token events.

Uses the Part 16 async model: stream the generator draft immediately, run the
Critic afterwards (for the ledger angle, deterministic gate only — no same-turn
rewrite), so the user sees text appear live instead of waiting for the full
plan → generate → critique → maybe-retry cycle.

on_event(kind, data): kind in {"meta","stage","token","done","error"}.
  stage payloads: {"stage": "classifying|planning|writing|reviewing", "detail": str}
"""
from datetime import datetime

from astro.transits import calculate_timing_confidence, get_transits_for_dasha_window
from db import store
from db.ledger import get_or_create_ledger, planner_view, update_ledger

from . import critic as critic_mod
from . import generator as gen_mod
from . import planner as planner_mod
from . import llm
from .chart_map import get_chart_slice, merge_chart_slices
from .classify import classify_domain, classify_query_type
from .prompts import STARSAGE_SYSTEM_PROMPT


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


def _stream_reading(user_id, session_id, message, chart, on_event, *, primary, secondary,
                    query_type, forced_domain=None):
    state = store.get_session_state(session_id)
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

    on_event("stage", {"stage": "writing", "detail": f"{planner_json.get('mechanism')} · {domain}"})
    response = gen_mod.stream_generator(message, chart_slice, planner_json, history,
                                        lambda d: on_event("token", {"text": d}))

    on_event("stage", {"stage": "reviewing", "detail": "grounding & quality check"})
    critic_json = critic_mod.run_critic(response, planner_json, ledger, chart_slice)

    update_ledger(user_id, domain, planner_json, critic_json)
    if secondary and not forced_domain:
        update_ledger(user_id, secondary, planner_json, critic_json)
    store.update_session_state(session_id, planner_json)
    store.increment_interaction_count(session_id)
    store.save_turn(session_id, user_id, "user", message, domain, query_type=query_type)
    store.save_turn(session_id, user_id, "assistant", response, domain, planner_json.get("mechanism"))
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
            for delta in llm.stream_llm("quality", STARSAGE_SYSTEM_PROMPT, history, user, 0.75, 900):
                acc.append(delta)
                on_event("token", {"text": delta})
            text = "".join(acc)
        except Exception as e:
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
        for delta in llm.stream_llm("quality", STARSAGE_SYSTEM_PROMPT, history, user, 0.8, 1000):
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
        on_event("error", {"error": f"{type(e).__name__}: {e}"})
