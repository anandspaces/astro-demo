"""Planner call (Part 11): assemble input, call LLM, parse JSON, fallback.

Fallback fixes: #14 per-domain house/dchart/karaka (not career-hardcoded),
#15 predictive fallback fills a real current-window, #16 mixed intent = predictive.
"""
import json

from . import llm
from .prompts import PLANNER_PROMPT

# Per-domain defaults for the fallback (bug #14). (primary_house, divisional_chart, karaka)
DOMAIN_DEFAULTS = {
    "career": (10, "D10", "amatyakaraka"),
    "relationship": (7, "D9", "darakaraka"),
    "wealth": (2, "D2", "atmakaraka"),
    "health": (1, None, "atmakaraka"),
    "property": (4, "D4", "atmakaraka"),
    "children": (5, "D7", "atmakaraka"),
    "spirituality": (9, None, "atmakaraka"),
    "travel": (12, None, "atmakaraka"),
    "fame": (10, "D10", "amatyakaraka"),
    "forecast": (1, None, "atmakaraka"),
    "general": (1, None, "atmakaraka"),
}

MECHANISMS = ["nakshatra", "house_lord_placement", "planets_in_house",
              "divisional_chart", "aspects_on_primary_house"]
AXES = ["behaviour", "consequence", "resistance", "limitation", "cost"]
PREDICTIVE = {"timing", "forecast", "mixed"}      # #16: mixed is predictive


def build_planner_input(user_message, chart_slice, ledger_view, session_state,
                        query_type, secondary_domain=None):
    return json.dumps({
        "user_message": user_message,
        "query_type": query_type,
        "secondary_domain": secondary_domain,
        "session_state": {
            "last_mechanism": session_state.get("last_mechanism"),
            "last_insight_axis": session_state.get("last_insight_axis"),
            "last_domain": session_state.get("last_domain"),
        },
        "ledger": ledger_view,
        "chart_slice": chart_slice,
    }, default=str)


def _current_window(chart_slice):
    """A machine-readable window from the current MD→AD→PD (fallback timing)."""
    d = chart_slice.get("dashas", {})
    md, ad, pd = d.get("current_MD", {}), d.get("current_AD", {}), d.get("current_PD", {})
    windows = []
    if pd:
        windows.append({"label": f"{md.get('planet')} MD → {ad.get('planet')} AD → {pd.get('planet')} PD",
                        "start": pd.get("start"), "end": pd.get("end")})
    for u in d.get("upcoming_PDs", [])[:1]:
        windows.append({"label": f"{ad.get('planet')} AD → {u.get('planet')} PD",
                        "start": u.get("start"), "end": u.get("end")})
    return windows


def build_fallback_planner(domain, query_type, session_state, chart_slice=None):
    house, dchart, karaka = DOMAIN_DEFAULTS.get(domain, DOMAIN_DEFAULTS["general"])

    last_m = session_state.get("last_mechanism")
    mechanism = next((m for m in MECHANISMS if m != last_m), MECHANISMS[0])
    last_a = session_state.get("last_insight_axis")
    axis = next((a for a in AXES if a != last_a), AXES[0])

    predictive = query_type in PREDICTIVE
    if predictive:
        mechanism = "dasha"

    karaka_name = None
    if chart_slice:
        karaka_name = chart_slice.get("special_factors", {}).get(karaka)

    return {
        "query_type": query_type,
        "response_structure": f"{query_type}_structure",
        "intent": "predictive" if predictive else "descriptive",
        "domain": domain,
        "secondary_domain": None,
        "primary_house": house,
        "divisional_chart": dchart,
        "mechanism": mechanism,
        "karaka": karaka_name,
        "insight_axis": axis,
        "timing_confidence": "medium" if predictive else "none",
        "timing_windows": _current_window(chart_slice) if (predictive and chart_slice) else [],
        "factors_to_use": [],
        "factors_to_avoid": [],
        "yoga_used": None,
        "checklist_items_used": [],
    }


def run_planner(user_message, chart_slice, ledger_view, session_state,
                query_type, primary_domain, secondary_domain=None):
    """Return a validated planner_json (always). Uses fallback in mock mode or on parse error."""
    if llm.is_mock():
        p = build_fallback_planner(primary_domain, query_type, session_state, chart_slice)
        p["secondary_domain"] = secondary_domain
        return p
    payload = build_planner_input(user_message, chart_slice, ledger_view, session_state,
                                  query_type, secondary_domain)
    try:
        raw = llm.call_llm("fast", PLANNER_PROMPT, payload, temp=0.3, max_tokens=600)
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(raw)
    except (json.JSONDecodeError, Exception):
        p = build_fallback_planner(primary_domain, query_type, session_state, chart_slice)
        p["secondary_domain"] = secondary_domain
        return p


def normalise_windows(planner_json):
    """Yield (label, start, end) for each timing window, tolerating str or dict form."""
    out = []
    for w in planner_json.get("timing_windows", []) or []:
        if isinstance(w, dict):
            out.append((w.get("label", ""), w.get("start"), w.get("end")))
        else:
            out.append((w, None, None))       # plain string; dates unparsed (bug #23 fallback)
    return out
