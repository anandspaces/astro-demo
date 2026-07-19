"""Planner call (Part 11): assemble input, call LLM, parse JSON, fallback.

Fallback fixes: #14 per-domain house/dchart/karaka (not career-hardcoded),
#15 predictive fallback fills a real current-window, #16 mixed intent = predictive.
"""
import json
import logging

from . import llm, prompts

log = logging.getLogger("starsage.planner")

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

# The mechanisms the Planner is allowed to choose (PLANNER_PROMPT step 4). Anything
# outside this set means the Planner invented a mechanism — the Generator preamble
# would then carry an instruction the system prompt has no structure for, so the
# plan is rejected and the deterministic fallback is used instead.
APPROVED_MECHANISMS = frozenset({
    "house_lord_placement", "planets_in_house", "nakshatra", "divisional_chart",
    "dasha", "aspects_on_primary_house", "yoga_activation",
})

# Rotation pool for the fallback: the descriptive mechanisms only ("dasha" is
# reserved for predictive intent, "yoga_activation" needs a yoga to activate).
MECHANISMS = ["nakshatra", "house_lord_placement", "planets_in_house",
              "divisional_chart", "aspects_on_primary_house"]
AXES = ["behaviour", "consequence", "resistance", "limitation", "cost"]
CLOSING_TYPES = ["hook", "observation", "ceiling_question"]
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
            "last_closing_type": session_state.get("last_closing_type"),
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


def _nakshatra_of_planet(chart_slice, planet):
    """The nakshatra a named planet occupies, for the preamble's nakshatra_target."""
    if not (chart_slice and planet):
        return None
    return (chart_slice.get("planets", {}).get(planet) or {}).get("nakshatra")


def _next_in_cycle(options, current):
    """The option after `current`, wrapping around. Picking "the first one that isn't
    the last one" instead would ping-pong between the first two entries forever, so a
    session that keeps hitting the fallback would only ever see two mechanisms."""
    if current in options:
        return options[(options.index(current) + 1) % len(options)]
    return options[0]


def build_fallback_planner(domain, query_type, session_state, chart_slice=None):
    house, dchart, karaka = DOMAIN_DEFAULTS.get(domain, DOMAIN_DEFAULTS["general"])

    mechanism = _next_in_cycle(MECHANISMS, session_state.get("last_mechanism"))
    axis = _next_in_cycle(AXES, session_state.get("last_insight_axis"))
    closing = _next_in_cycle(CLOSING_TYPES, session_state.get("last_closing_type"))

    predictive = query_type in PREDICTIVE
    if predictive:
        mechanism = "dasha"

    karaka_name = None
    if chart_slice:
        karaka_name = chart_slice.get("special_factors", {}).get(karaka)

    # Same domain as last turn ⇒ the basics are already covered, so go a layer deeper.
    depth = 2 if session_state.get("last_domain") == domain else 1

    return {
        "query_type": query_type,
        "response_structure": f"{query_type}_structure",
        "intent": "predictive" if predictive else "descriptive",
        "domain": domain,
        "secondary_domain": None,
        "primary_house": house,
        "secondary_houses": [],
        "divisional_chart": dchart,
        "mechanism": mechanism,
        "karaka": karaka_name,
        "nakshatra_target": _nakshatra_of_planet(chart_slice, karaka_name),
        "insight_axis": axis,
        "depth_level": depth,
        "closing_type": closing,
        "identity_mirror": False,
        "comparative_analysis": False,
        "forecast_domains": ["career", "relationship", "wealth", "health"] if query_type == "forecast" else [],
        "timing_confidence": "medium" if predictive else "none",
        "timing_windows": _current_window(chart_slice) if (predictive and chart_slice) else [],
        "factors_to_use": [],
        "factors_to_avoid": [],
        "yoga_used": None,
        "checklist_items_used": [],
    }


def validate_plan(plan, query_type):
    """Return None if the Planner's JSON is usable, else a reason string.

    The mechanism check is the important one: an unapproved (hallucinated) mechanism
    reaches the Generator as an instruction the system prompt defines no structure
    for, and the reading is written on an invented method. Rejecting here costs one
    deterministic fallback plan; accepting costs the whole response."""
    if not isinstance(plan, dict):
        return f"not a JSON object ({type(plan).__name__})"
    mechanism = plan.get("mechanism")
    if mechanism not in APPROVED_MECHANISMS:
        return f"mechanism {mechanism!r} not in approved list"
    axis = plan.get("insight_axis")
    if axis not in AXES:
        return f"insight_axis {axis!r} not in {AXES}"
    if not plan.get("domain"):
        return "missing domain"
    if query_type in PREDICTIVE and plan.get("intent") not in ("predictive", "mixed"):
        return f"intent {plan.get('intent')!r} is not predictive for query_type {query_type!r}"
    return None


def apply_plan_defaults(plan, domain, query_type, session_state, chart_slice=None):
    """Fill fields the Planner prompt may not emit yet, so the Generator preamble
    always renders a complete plan. Never overwrites a value the Planner supplied."""
    base = build_fallback_planner(domain, query_type, session_state, chart_slice)
    for key in ("secondary_houses", "depth_level", "closing_type", "nakshatra_target",
                "identity_mirror", "comparative_analysis", "forecast_domains",
                "response_structure", "intent", "primary_house", "karaka"):
        if plan.get(key) in (None, "", []):
            plan[key] = base[key]
    return plan


def run_planner(user_message, chart_slice, ledger_view, session_state,
                query_type, primary_domain, secondary_domain=None):
    """Return a validated planner_json (always). Uses fallback in mock mode or on parse error."""
    if llm.is_mock():
        p = build_fallback_planner(primary_domain, query_type, session_state, chart_slice)
        p["secondary_domain"] = secondary_domain
        return p
    payload = build_planner_input(user_message, chart_slice, ledger_view, session_state,
                                  query_type, secondary_domain)
    plan, reject_reason = None, None
    try:
        raw = llm.call_llm("fast", prompts.get_prompt("planner"), payload, temp=0.3, max_tokens=600)
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        plan = json.loads(raw)
        reject_reason = validate_plan(plan, query_type)
    except Exception as e:
        reject_reason = f"{type(e).__name__}: {e}"

    if reject_reason:
        log.warning("planner output rejected (%s) — using deterministic fallback "
                    "[domain=%s query_type=%s]", reject_reason, primary_domain, query_type)
        plan = build_fallback_planner(primary_domain, query_type, session_state, chart_slice)
    else:
        plan = apply_plan_defaults(plan, primary_domain, query_type, session_state, chart_slice)
    plan["secondary_domain"] = secondary_domain
    return plan


def normalise_windows(planner_json):
    """Yield (label, start, end) for each timing window, tolerating str or dict form."""
    out = []
    for w in planner_json.get("timing_windows", []) or []:
        if isinstance(w, dict):
            out.append((w.get("label", ""), w.get("start"), w.get("end")))
        else:
            out.append((w, None, None))       # plain string; dates unparsed (bug #23 fallback)
    return out
