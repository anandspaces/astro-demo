"""Critic call (Part 13) + deterministic gate. Synchronous, blocking (bug #22 decision).

Runs precheck (code) first, then the LLM Critic for judgment calls. In mock mode
the LLM step is skipped and the verdict comes from the deterministic gate plus a
heuristic angle summary.
"""
import json
import logging

from . import llm, precheck, prompts

log = logging.getLogger("starsage.critic")

# A failed review triggers at most one same-turn rewrite. Only these severities are
# worth spending that second generation on; a "minor" nit is not (the rewrite costs a
# full quality-tier call and often trades one small flaw for another).
RETRY_SEVERITIES = frozenset({"critical", "moderate"})


def issue_text(issue):
    """Issues arrive either as plain strings (old/mock format) or as
    {"issue","severity"} objects (current Critic prompt). Read both."""
    if isinstance(issue, dict):
        return str(issue.get("issue") or issue.get("text") or issue)
    return str(issue)


def _severity_of(issue, severities_map):
    if isinstance(issue, dict) and issue.get("severity"):
        return str(issue["severity"]).strip().lower()
    mapped = (severities_map or {}).get(issue_text(issue))
    return str(mapped).strip().lower() if mapped else None


def should_retry(critic_json):
    """Whether a failed critique warrants one rewrite.

    Retry when the Critic reports a critical/moderate issue. If the Critic emitted no
    severities at all (older prompt, mock mode, or a malformed reply) we retry on any
    failure — so behaviour is unchanged until the Critic prompt starts labelling
    severity. Deterministic precheck issues (word count, hook length, tense, repeated
    yoga) are hard failures and always retry-worthy."""
    if critic_json.get("pass", True):
        return False
    if critic_json.get("hard_fail"):
        return True
    issues = critic_json.get("issues") or []
    severities = [s for s in (_severity_of(i, critic_json.get("severities")) for i in issues) if s]
    if not severities:
        return True                       # no severity information → old behaviour
    return any(s in RETRY_SEVERITIES for s in severities)


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
            "hard_fail": bool(hard_issues),
            "issues": hard_issues,
            "rewrite_instruction": ("; ".join(hard_issues)) if hard_issues else None,
            "angle_summary": _heuristic_angle(planner_json),
            "prediction_summary": (planner_json.get("timing_windows") or [None])[0]
            if planner_json.get("intent") == "predictive" else None,
        }

    try:
        raw = llm.call_llm("fast", prompts.get_prompt("critic"),
                           build_critic_input(response, planner_json, ledger, chart_slice),
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
        seen = {issue_text(i) for i in (cj.get("issues") or [])}
        cj["issues"] = list(cj.get("issues") or []) + [h for h in hard_issues if h not in seen]
        cj["pass"] = False
        cj["hard_fail"] = True            # precheck failures always earn the rewrite
        cj["rewrite_instruction"] = cj.get("rewrite_instruction") or "; ".join(hard_issues)
    cj.setdefault("angle_summary", _heuristic_angle(planner_json))
    return cj
