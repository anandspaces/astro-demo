"""Generator call (Part 12). Real path uses the quality model; mock path renders a
templated reading from the plan + chart so the pipeline is fully runnable offline."""
import logging
import time

from . import llm

log = logging.getLogger("starsage.generator")
from .format_chart import format_chart_for_generator, format_chart_minimal
from . import prompts


def _estimate_tokens(text):
    return int(len(text.split()) * 1.35)


def _format_timing_support(planner_json):
    """Render the plan's dated timing windows + per-window future transits so the
    Generator actually SEES the transit support for predictive queries (fix, 2026-07:
    these were computed onto planner_json but never reached the Generator payload,
    so timing responses were written blind to their own transit data)."""
    windows = planner_json.get("timing_windows") or []
    future = planner_json.get("future_transits") or {}
    if not windows and not future:
        return ""
    lines = ["\nTIMING WINDOWS (cite these dated windows, most significant first):"]
    for w in windows:
        if isinstance(w, dict):
            label, start, end = w.get("label", ""), w.get("start"), w.get("end")
            lines.append(f"- {label}" + (f": {start}–{end}" if start and end else ""))
        else:
            lines.append(f"- {w}")
    if future:
        lines.append("FUTURE TRANSIT SUPPORT (slow planets at each window's midpoint):")
        for label, transits in future.items():
            bits = ", ".join(
                f"{p} {t.get('sign')} ({t.get('house_from_moon')}H from Moon)"
                for p, t in transits.items())
            lines.append(f"- {label}: {bits}")
    confidence = planner_json.get("timing_confidence")
    if confidence:
        lines.append(f"TIMING CONFIDENCE: {confidence}")
    return "\n".join(lines)


def _bullets(items, empty="(none specified)"):
    """One item per line, so a long factor list stays readable in the preamble."""
    items = [str(i) for i in (items or []) if i]
    return "\n".join(f"- {i}" for i in items) if items else empty


def _preamble_fields(planner_json, rotation):
    """Every placeholder the preamble template may reference. Conditional blocks
    render as "" when they don't apply, so one template covers all query types.
    A block that is present ends with a newline and never starts with one."""
    p, rot = planner_json, (rotation or {})
    intent = p.get("intent")
    mechanism = p.get("mechanism")
    depth = p.get("depth_level") or 1

    yoga = p.get("yoga_used")
    yoga_line = (f"YOGA TO SURFACE: {yoga} — name it, then explain how it forms "
                 f"from the placements in the chart data.\n") if yoga else ""

    timing = _format_timing_support(p) if intent in ("predictive", "mixed") else ""
    timing_block = f"{timing.strip()}\n" if timing.strip() else ""

    forecast_domains = p.get("forecast_domains") or []
    forecast_domains_line = (
        f"FORECAST DOMAINS (cover each, anchored to its own chart factor): "
        f"{', '.join(str(d) for d in forecast_domains)}\n"
    ) if p.get("query_type") == "forecast" and forecast_domains else ""

    flags = []
    if p.get("identity_mirror"):
        flags.append("- IDENTITY MIRROR: reflect who this person is structurally, "
                     "not merely what happens to them.")
    if p.get("comparative_analysis"):
        flags.append("- COMPARATIVE: contrast the two sides of this question explicitly, "
                     "and say which the chart favours.")
    flags_block = ("\n".join(flags) + "\n") if flags else ""

    depth_reminder = (
        "DEPTH: this is a follow-up on ground already covered. Go a layer deeper than "
        "an introductory reading — assume the basics are known and give the mechanism "
        "underneath them.\n"
    ) if depth and int(depth) >= 2 else ""

    chain_reminder = (
        "CHAIN THE LOGIC: state the placement, then what that placement does, then how "
        "it shows up in this person's life. Do not stop at naming the placement.\n"
    ) if mechanism in ("planets_in_house", "house_lord_placement") else ""

    return dict(
        query_type=p.get("query_type"),
        response_structure=p.get("response_structure"),
        intent=intent,
        domain=p.get("domain"),
        secondary_domain=p.get("secondary_domain") or "(none)",
        primary_house=p.get("primary_house"),
        secondary_houses=", ".join(str(h) for h in (p.get("secondary_houses") or [])) or "(none)",
        mechanism=mechanism,
        nakshatra_target=p.get("nakshatra_target") or "(none)",
        karaka=p.get("karaka") or "(none)",
        insight_axis=p.get("insight_axis"),
        depth_level=depth,
        divisional_chart=p.get("divisional_chart") or "(none)",
        closing_type=p.get("closing_type") or "hook",
        factors_to_use=_bullets(p.get("factors_to_use"), "(planner did not specify)"),
        factors_to_avoid=_bullets(p.get("factors_to_avoid"), "(none)"),
        yoga_used=yoga or "none",          # legacy field: older overrides reference it
        yoga_line=yoga_line,
        timing_block=timing_block,
        forecast_domains_line=forecast_domains_line,
        flags_block=flags_block,
        depth_reminder=depth_reminder,
        chain_reminder=chain_reminder,
        last_mechanism=rot.get("last_mechanism") or "(none)",
        last_insight_axis=rot.get("last_insight_axis") or "(none)",
        last_domain=rot.get("last_domain") or "(none)",
        last_closing_type=rot.get("last_closing_type") or "(none)",
    )


def build_preamble(planner_json, rotation=None):
    """Render the per-turn plan preamble. A broken override (references a field we
    don't supply) falls back to the shipped default rather than failing the turn."""
    fields = _preamble_fields(planner_json, rotation)
    try:
        return prompts.get_prompt("preamble").format(**fields)
    except (KeyError, IndexError, ValueError) as e:
        log.warning("preamble override failed to render (%s: %s) — using default", type(e).__name__, e)
        return prompts.default_prompt("preamble").format(**fields)


def build_generator_payload(user_message, chart_slice, planner_json, rotation=None,
                            minimal=False, rewrite_instruction=None):
    """Return (system, user).

    CRITICAL (2026-07): the plan preamble goes in the SYSTEM message, never in the
    user message. Sent as a user turn it reads as the *user* instructing the model
    to follow a plan and override its own instructions — which models treat as an
    injection attempt and ignore, leaving the Generator with no mechanism, axis,
    depth or closing guidance. The user message now carries only chart data and the
    actual question."""
    system = prompts.get_prompt("system") + "\n\n" + build_preamble(planner_json, rotation)
    if rewrite_instruction:
        # Critic feedback is pipeline-side too — same reasoning as the preamble.
        system += f"\nREVISION REQUIRED ON THIS ATTEMPT: {rewrite_instruction}\n"
    chart_txt = format_chart_minimal(chart_slice) if minimal else format_chart_for_generator(chart_slice)
    user = f"{chart_txt}\n\nUSER QUESTION: {user_message}"
    return system, user


def _mock_reading(user_message, chart_slice, planner_json):
    """Deterministic templated reading — placeholder for a real LLM Generator."""
    lag = chart_slice.get("lagna", {})
    d = chart_slice.get("dashas", {})
    md, ad, pd = d.get("current_MD", {}), d.get("current_AD", {}), d.get("current_PD", {})
    domain = planner_json.get("domain")
    axis = planner_json.get("insight_axis")
    factors = planner_json.get("factors_to_use") or []
    para_factors = " ".join(factors) if factors else (
        f"With {lag.get('sign')} rising and its lord {lag.get('lord')} shaping your path, "
        f"the {domain} question is read through the current dasha."
    )
    windows = planner_json.get("timing_windows") or []
    win_txt = ""
    if windows:
        labels = [w["label"] if isinstance(w, dict) else w for w in windows]
        win_txt = " The periods to watch: " + "; ".join(labels) + "."
    body = (
        f"[MOCK GENERATOR — set STARSAGE_PROVIDER to claude/gpt/gemini for real readings]\n\n"
        f"On your {domain} question: {para_factors} "
        f"Right now you are running {md.get('planet')} Mahadasha, {ad.get('planet')} Antardasha, "
        f"{pd.get('planet')} Pratyantardasha, and this is the lens through which the theme expresses. "
        f"Seen through the axis of {axis}, the chart points less to chance and more to the pattern you "
        f"keep meeting.{win_txt} The mechanism here ({planner_json.get('mechanism')}) is what a senior "
        f"astrologer would weigh first, and it favours steady, deliberate movement over sudden leaps."
    )
    hook = "Shall I show you what shifts next?"
    return f"{body}\n\n{hook}"


def _mock_chunks(text):
    """Yield a mock reading word-by-word so the UI can stream it."""
    words = text.split(" ")
    for i in range(0, len(words), 2):
        yield " ".join(words[i:i + 2]) + " "


def stream_generator(user_message, chart_slice, planner_json, history, on_token, rotation=None):
    """Stream the reading, calling on_token(delta) per chunk. Returns full text."""
    if llm.is_mock():
        full = _mock_reading(user_message, chart_slice, planner_json)
        for chunk in _mock_chunks(full):
            on_token(chunk)
        return full

    system, user = build_generator_payload(user_message, chart_slice, planner_json, rotation)
    parts_tokens = _estimate_tokens(system) + _estimate_tokens(user) + sum(_estimate_tokens(h["content"]) for h in history)
    if parts_tokens > 7000:
        history = history[-4:]
        system, user = build_generator_payload(user_message, chart_slice, planner_json,
                                               rotation, minimal=True)

    acc = []
    try:
        for delta in llm.stream_llm("quality", system, history, user, temp=0.75, max_tokens=1100):
            acc.append(delta)
            on_token(delta)
    except Exception as e:
        log.warning("generator stream failed: %s: %s", type(e).__name__, e)

    text = "".join(acc)
    if text.strip():
        return text            # usable text streamed (even if it errored partway) — keep it

    # Nothing usable streamed → clean non-streamed fallback (has its own retry/fallback).
    # We only reach here when no tokens were emitted, so there is no double-emit.
    text = run_generator(user_message, chart_slice, planner_json, history, rotation=rotation)
    on_token(text)
    return text


def _quality_call(system, history, user):
    """One quality-tier generation. An empty/whitespace completion is treated as a
    failure so the caller's retry/fallback path runs instead of returning a blank."""
    text = llm.call_llm_with_history("quality", system, history, user, temp=0.75, max_tokens=1100)
    if not text or not text.strip():
        raise RuntimeError("empty completion from provider")
    return text


def run_generator(user_message, chart_slice, planner_json, history, rewrite_instruction=None,
                  rotation=None):
    if llm.is_mock():
        return _mock_reading(user_message, chart_slice, planner_json)

    system, user = build_generator_payload(user_message, chart_slice, planner_json, rotation,
                                           rewrite_instruction=rewrite_instruction)
    # Token pressure -> trim history to 4 turns and use minimal chart (Part 14).
    parts_tokens = _estimate_tokens(system) + _estimate_tokens(user) + sum(_estimate_tokens(h["content"]) for h in history)
    if parts_tokens > 7000:
        history = history[-4:]
        system, user = build_generator_payload(user_message, chart_slice, planner_json, rotation,
                                               minimal=True, rewrite_instruction=rewrite_instruction)

    provider, model = llm.resolve_provider(), llm.model_for("quality")
    try:
        return _quality_call(system, history, user)
    except Exception as e:
        log.warning("generator LLM call failed (provider=%s model=%s), retrying: %s: %s",
                    provider, model, type(e).__name__, e)
        time.sleep(2)
        try:
            return _quality_call(system, history, user)
        except Exception as e:
            log.error("generator LLM call failed after retry (provider=%s model=%s): %s: %s",
                      provider, model, type(e).__name__, e, exc_info=True)
            return "StarSage is temporarily unavailable. Please try again in a moment."
