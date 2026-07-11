"""Generator call (Part 12). Real path uses the quality model; mock path renders a
templated reading from the plan + chart so the pipeline is fully runnable offline."""
import time

from . import llm
from .format_chart import format_chart_for_generator, format_chart_minimal
from .prompts import PIPELINE_PREAMBLE, STARSAGE_SYSTEM_PROMPT


def _estimate_tokens(text):
    return int(len(text.split()) * 1.35)


def build_generator_input(user_message, chart_slice, planner_json, minimal=False):
    chart_txt = format_chart_minimal(chart_slice) if minimal else format_chart_for_generator(chart_slice)
    preamble = PIPELINE_PREAMBLE.format(
        query_type=planner_json.get("query_type"),
        response_structure=planner_json.get("response_structure"),
        mechanism=planner_json.get("mechanism"),
        insight_axis=planner_json.get("insight_axis"),
        factors_to_use="; ".join(planner_json.get("factors_to_use", []) or []) or "(planner did not specify)",
        factors_to_avoid="; ".join(planner_json.get("factors_to_avoid", []) or []) or "(none)",
        yoga_used=planner_json.get("yoga_used") or "none",
        last_mechanism="(none)", last_insight_axis="(none)", last_domain="(none)",
    )
    return f"{preamble}\n\n{chart_txt}\n\nUSER QUESTION: {user_message}"


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


def stream_generator(user_message, chart_slice, planner_json, history, on_token):
    """Stream the reading, calling on_token(delta) per chunk. Returns full text."""
    if llm.is_mock():
        full = _mock_reading(user_message, chart_slice, planner_json)
        for chunk in _mock_chunks(full):
            on_token(chunk)
        return full

    user = build_generator_input(user_message, chart_slice, planner_json)
    system = STARSAGE_SYSTEM_PROMPT
    parts_tokens = _estimate_tokens(system) + _estimate_tokens(user) + sum(_estimate_tokens(h["content"]) for h in history)
    if parts_tokens > 7000:
        history = history[-4:]
        user = build_generator_input(user_message, chart_slice, planner_json, minimal=True)

    acc = []
    try:
        for delta in llm.stream_llm("quality", system, history, user, temp=0.75, max_tokens=900):
            acc.append(delta)
            on_token(delta)
        return "".join(acc)
    except Exception:
        # Fall back to a single non-streamed call.
        text = run_generator(user_message, chart_slice, planner_json, history)
        on_token(text)
        return text


def run_generator(user_message, chart_slice, planner_json, history, rewrite_instruction=None):
    if llm.is_mock():
        return _mock_reading(user_message, chart_slice, planner_json)

    user = build_generator_input(user_message, chart_slice, planner_json)
    if rewrite_instruction:
        user += f"\n\nREVISION REQUIRED: {rewrite_instruction}"

    system = STARSAGE_SYSTEM_PROMPT
    # Token pressure -> trim history to 4 turns and use minimal chart (Part 14).
    parts_tokens = _estimate_tokens(system) + _estimate_tokens(user) + sum(_estimate_tokens(h["content"]) for h in history)
    if parts_tokens > 7000:
        history = history[-4:]
        user = build_generator_input(user_message, chart_slice, planner_json, minimal=True)

    try:
        return llm.call_llm_with_history("quality", system, history, user, temp=0.75, max_tokens=900)
    except Exception:
        time.sleep(2)
        try:
            return llm.call_llm_with_history("quality", system, history, user, temp=0.75, max_tokens=900)
        except Exception:
            return "StarSage is temporarily unavailable. Please try again in a moment."
