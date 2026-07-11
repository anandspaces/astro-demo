"""Deterministic Critic pre-checks (my recommended reconciliation of bug #22).

The checkable Part-13 criteria (word count, hook length, tense, yoga membership)
run in code BEFORE the LLM Critic — cheaper and more reliable than asking a model
to count words. The LLM Critic then handles the judgment calls (grounding, factor
use, structure).
"""
import re

PAST_TENSE_HINTS = re.compile(
    r"\b(happened|occurred|was|were|had been|did|got married|you got|you were|you had)\b",
    re.IGNORECASE,
)


def word_count(text):
    return len(text.split())


def last_sentence(text):
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    return parts[-1] if parts else ""


def deterministic_issues(response, planner_json, ledger):
    """Return a list of hard, mechanical issues. Empty list = passes the cheap gate."""
    issues = []
    wc = word_count(response)
    if wc < 400:
        issues.append(f"word_count_low ({wc} < 400)")
    elif wc > 550:
        issues.append(f"word_count_high ({wc} > 550)")

    hook = last_sentence(response)
    if word_count(hook) > 15:
        issues.append(f"hook_too_long ({word_count(hook)} words)")

    intent = planner_json.get("intent")
    if intent == "predictive" and PAST_TENSE_HINTS.search(response):
        issues.append("predictive_response_uses_past_tense")

    # Thematic responses should carry no explicit timing windows.
    if planner_json.get("query_type") == "thematic":
        if re.search(r"\b20\d{2}\b", response):
            issues.append("thematic_response_contains_year")

    # A yoga already surfaced should not reappear (unless the plan re-uses it deliberately).
    already = set(ledger.get("yogas_mentioned", []))
    reused = [y for y in already if y.replace("_", " ").lower() in response.lower()
              and y != planner_json.get("yoga_used")]
    if reused:
        issues.append(f"repeats_prior_yoga: {reused}")

    return issues
