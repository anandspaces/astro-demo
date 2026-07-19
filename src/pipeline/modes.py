"""The four pipeline modes (Part 10). Synchronous Critic with deterministic gate.

Depends on the `db` package (store + ledger) and the `astro` engine (transits).
"""
import logging
from datetime import datetime

from astro.transits import calculate_timing_confidence, get_transits_for_dasha_window
from db import store
from db.ledger import get_or_create_ledger, planner_view, update_ledger

from . import critic as critic_mod
from . import generator as gen_mod
from . import planner as planner_mod
from .chart_map import get_chart_slice, merge_chart_slices
from .classify import classify_domain, classify_query_type
from . import llm, prompts

log = logging.getLogger("starsage.modes")


def _persist_session_state(session_id, planner_json):
    """Write session rotation state, catching+logging silent write failures (a dropped
    write here breaks mechanism rotation on every later turn — priority fix)."""
    try:
        if not store.update_session_state(session_id, planner_json):
            log.error("session-state write no-op for session=%s (row missing?); "
                      "last_mechanism NOT persisted", session_id)
    except Exception as e:
        log.error("session-state write FAILED for session=%s: %s: %s",
                  session_id, type(e).__name__, e, exc_info=True)


def _attach_future_transits(planner_json, chart):
    """For predictive plans with dated windows, add slow-planet transits + confidence."""
    lagna_sign = chart["lagna"]["sign"]
    moon_sign = chart["planets"]["Moon"]["sign"]
    future = {}
    for label, start, end in planner_mod.normalise_windows(planner_json):
        if not (start and end):
            continue                       # unparsed string window (bug #23 fallback) — skip transit lookup
        try:
            s = datetime.strptime(start, "%Y-%m-%d")
            e = datetime.strptime(end, "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        future[label] = get_transits_for_dasha_window(s, e, lagna_sign, moon_sign)
    if future:
        planner_json["future_transits"] = future
        planner_json["timing_confidence"] = calculate_timing_confidence(
            dasha_support=True,
            transit_support=True,
            divisional_support=planner_json.get("divisional_chart") is not None,
        )
    return planner_json


# ---- Mode 1: Synthesis ----------------------------------------------------
def handle_synthesis(user_id, session_id, chart):
    all_ledgers = store.get_all_domain_ledgers(user_id)
    history = store.get_recent_history(session_id, limit=6)
    directive = (
        "SYNTHESIS MODE — normal mechanism rotation does not apply. Review the cross-domain "
        "ledger. Identify the single most significant structural pattern across multiple life "
        "domains, grounded in specific planetary combinations. Name it. Show how it manifests "
        "differently across domains. Connect it to the current dasha. Do not answer any specific "
        "question. No continuation hook. End with one declarative statement about what this "
        "pattern means for 2026."
    )
    if llm.is_mock():
        md = chart["dashas"]["current_MD"]["planet"]
        ak = chart["special_factors"]["atmakaraka"]
        response = (
            f"[MOCK SYNTHESIS] Across your questions one structure keeps surfacing: {ak} as "
            f"Atmakaraka threading career, relationship and wealth alike, now activated under your "
            f"{md} Mahadasha. The same instinct that steadies your work also governs how you attach "
            f"and how you build. In 2026 this pattern asks you to lead with that core, not around it."
        )
    else:
        from .format_chart import format_chart_for_generator
        user = f"{directive}\n\nCROSS-DOMAIN LEDGER:\n{all_ledgers}\n\n{format_chart_for_generator(get_chart_slice(chart,'forecast'))}"
        response = llm.call_llm_with_history("quality", prompts.get_prompt("system"), history, user, temp=0.8, max_tokens=1000)

    store.save_turn(session_id, user_id, "user", "[synthesis triggered]", "synthesis")
    store.save_turn(session_id, user_id, "assistant", response, "synthesis", "synthesis")
    store.increment_interaction_count(session_id)
    return response


# ---- Mode 2: Affirmation --------------------------------------------------
def handle_affirmation(user_id, session_id, user_message, chart):
    state = store.get_session_state(session_id)
    domain = state.get("last_domain") or "general"
    last_assistant = store.get_last_assistant_turn(session_id)
    from .precheck import last_sentence
    cue = last_sentence(last_assistant)
    chart_slice = get_chart_slice(chart, domain)
    history = store.get_recent_history(session_id, limit=6)

    if llm.is_mock():
        response = (
            f"[MOCK AFFIRMATION] Picking up from '{cue}': staying with your {domain} thread, the same "
            f"dasha lord continues to shape what unfolds next, and the detail worth naming now is how "
            f"steadily it builds rather than whether it arrives."
        )
    else:
        user = (f"The user affirmed with: \"{user_message}\". Address this continuation cue directly and "
                f"immediately: {cue}. Do not reintroduce context. Pick up from where the last response ended.")
        response = llm.call_llm_with_history("quality", prompts.get_prompt("system"), history, user, temp=0.75, max_tokens=1100)

    store.save_turn(session_id, user_id, "user", user_message, domain)
    store.save_turn(session_id, user_id, "assistant", response, domain)
    store.increment_interaction_count(session_id)
    return response


# ---- Mode 3: Forecast -----------------------------------------------------
def handle_forecast(user_id, session_id, user_message, chart):
    state = store.get_session_state(session_id)
    ledger = get_or_create_ledger(user_id, "forecast")
    chart_slice = get_chart_slice(chart, "forecast")
    history = store.get_recent_history(session_id, limit=6)

    planner_json = planner_mod.run_planner(
        user_message, chart_slice, planner_view(ledger), state,
        query_type="forecast", primary_domain="forecast",
    )
    planner_json = _attach_future_transits(planner_json, chart)
    return _generate_and_finalise(user_id, session_id, user_message, chart_slice, planner_json,
                                  history, ledger, "forecast", None, rotation=state)


# ---- Mode 4: Standard -----------------------------------------------------
def handle_standard(user_id, session_id, user_message, chart):
    query_type = classify_query_type(user_message)
    domains = classify_domain(user_message)
    primary, secondary = domains[0], (domains[1] if len(domains) > 1 else None)

    state = store.get_session_state(session_id)
    ledger = get_or_create_ledger(user_id, primary)
    chart_slice = get_chart_slice(chart, primary)
    if secondary:
        chart_slice = merge_chart_slices(chart_slice, get_chart_slice(chart, secondary))
    history = store.get_recent_history(session_id, limit=6)

    planner_json = planner_mod.run_planner(
        user_message, chart_slice, planner_view(ledger), state,
        query_type=query_type, primary_domain=primary, secondary_domain=secondary,
    )
    if query_type in ("timing", "mixed"):
        planner_json = _attach_future_transits(planner_json, chart)

    return _generate_and_finalise(user_id, session_id, user_message, chart_slice, planner_json,
                                  history, ledger, primary, secondary, query_type, rotation=state)


def _generate_and_finalise(user_id, session_id, user_message, chart_slice, planner_json,
                           history, ledger, primary_domain, secondary_domain, query_type=None,
                           rotation=None):
    response = gen_mod.run_generator(user_message, chart_slice, planner_json, history,
                                     rotation=rotation)
    critic_json = critic_mod.run_critic(response, planner_json, ledger, chart_slice)

    if critic_mod.should_retry(critic_json):
        retry = gen_mod.run_generator(user_message, chart_slice, planner_json, history,
                                      rewrite_instruction=critic_json.get("rewrite_instruction"),
                                      rotation=rotation)
        response = retry            # always pass through after one retry

    update_ledger(user_id, primary_domain, planner_json, critic_json)
    if secondary_domain:
        update_ledger(user_id, secondary_domain, planner_json, critic_json)
    _persist_session_state(session_id, planner_json)
    store.increment_interaction_count(session_id)
    store.save_turn(session_id, user_id, "user", user_message, primary_domain, query_type=query_type)
    store.save_turn(session_id, user_id, "assistant", response, primary_domain,
                    planner_json.get("mechanism"),
                    insight_axis=planner_json.get("insight_axis"),
                    closing_type=planner_json.get("closing_type"))
    return response
