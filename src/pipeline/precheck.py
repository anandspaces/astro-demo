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

# Response length target. Tightened from 400-550 to 250-350 (priority fix, 2026-07):
# the wider band let responses run padded. Keep prompts.py + CRITIC_PROMPT in sync.
WORD_MIN = 250
WORD_MAX = 350

# Density check (priority fix, 2026-07): two consecutive sentences that convey the
# same information in different wording are the primary cause of padded responses.
# Deterministic pre-check flags high content-word overlap between adjacent sentences;
# the LLM Critic (CRITIC_PROMPT) also judges this for cases wording alone won't catch.
_STOPWORDS = frozenset(
    "a an the this that these those and or but so of to in on at for with from by as "
    "is are was were be been being will would can could may might your you yours it its "
    "his her their they them he she i we our not no more most very much also then than "
    "which who what when where how why into over under about through here there".split()
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
DENSITY_OVERLAP_THRESHOLD = 0.6      # Jaccard on content words; conservative to avoid false positives


def word_count(text):
    return len(text.split())


def _split_sentences(text):
    return [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


def last_sentence(text):
    parts = _split_sentences(text)
    return parts[-1] if parts else ""


def _content_words(sentence):
    words = re.findall(r"[a-z]+", sentence.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def redundant_consecutive_pair(text):
    """Return (i, jaccard) of the first adjacent sentence pair whose content-word
    overlap meets the threshold, else None. Used to flag padded, self-repeating prose."""
    sentences = _split_sentences(text)
    for i in range(len(sentences) - 1):
        a, b = _content_words(sentences[i]), _content_words(sentences[i + 1])
        if len(a) < 4 or len(b) < 4:
            continue                     # too short to judge; skip to avoid false positives
        overlap = len(a & b) / len(a | b)
        if overlap >= DENSITY_OVERLAP_THRESHOLD:
            return i, round(overlap, 2)
    return None


def deterministic_issues(response, planner_json, ledger):
    """Return a list of hard, mechanical issues. Empty list = passes the cheap gate."""
    issues = []
    wc = word_count(response)
    if wc < WORD_MIN:
        issues.append(f"word_count_low ({wc} < {WORD_MIN})")
    elif wc > WORD_MAX:
        issues.append(f"word_count_high ({wc} > {WORD_MAX})")

    hook = last_sentence(response)
    if word_count(hook) > 15:
        issues.append(f"hook_too_long ({word_count(hook)} words)")

    dup = redundant_consecutive_pair(response)
    if dup:
        issues.append(f"redundant_consecutive_sentences (pair #{dup[0]}, overlap {dup[1]})")

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
