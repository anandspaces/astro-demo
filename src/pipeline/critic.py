"""Critic call (Part 13) + deterministic gate. Synchronous, blocking (bug #22 decision).

Runs precheck (code) first, then the LLM Critic for judgment calls. In mock mode
the LLM step is skipped and the verdict comes from the deterministic gate plus a
heuristic angle summary.
"""
import json

from . import llm, precheck
from .prompts import CRITIC_PROMPT


def _heuristic_angle(planner_json):
    return f"{planner_json.get('mechanism')} on {planner_json.get('domain')} via {planner_json.get('insight_axis')}"


def build_critic_input(response, planner_json, ledger, chart_slice):
    return json.dumps({
        "draft_response": response,
        "reading_plan": planner_json,
        "ledger": {
            "answered_angles": ledger.get("answered_angles", [])[-10:],
            "yogas_mentioned": ledger.get("yogas_mentioned", []),
        },
        "chart_slice": chart_slice,
    }, default=str)


def run_critic(response, planner_json, ledger, chart_slice):
    """Return critic_json. Deterministic issues always included; LLM adds judgment."""
    hard_issues = precheck.deterministic_issues(response, planner_json, ledger)

    if llm.is_mock():
        return {
            "pass": len(hard_issues) == 0,
            "issues": hard_issues,
            "rewrite_instruction": ("; ".join(hard_issues)) if hard_issues else None,
            "angle_summary": _heuristic_angle(planner_json),
            "prediction_summary": (planner_json.get("timing_windows") or [None])[0]
            if planner_json.get("intent") == "predictive" else None,
        }

    try:
        raw = llm.call_llm("fast", CRITIC_PROMPT, build_critic_input(response, planner_json, ledger, chart_slice),
                           temp=0.2, max_tokens=350)
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        cj = json.loads(raw)
    except Exception:
        cj = {
            "pass": True,
            "issues": [],
            "rewrite_instruction": None,
            "angle_summary": _heuristic_angle(planner_json),
            "prediction_summary": "",
        }

    # Merge deterministic issues: a hard failure overrides an LLM pass.
    if hard_issues:
        cj["issues"] = list(dict.fromkeys((cj.get("issues") or []) + hard_issues))
        cj["pass"] = False
        cj["rewrite_instruction"] = cj.get("rewrite_instruction") or "; ".join(hard_issues)
    cj.setdefault("angle_summary", _heuristic_angle(planner_json))
    return cj
