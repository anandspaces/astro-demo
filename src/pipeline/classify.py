"""Domain and query-type classification (Part 9).

Keyword matching is word-boundary anchored (fix, 2026-07): plain substring matching
fired on "rent" inside "parent"/"current"/"different" and "earn" inside "learn",
routing questions to a domain nothing in them was about.
"""
import re

FORECAST_TRIGGERS = [
    "next month", "next year", "next week", "coming months",
    "how will my month", "how will my year", "how will next",
    "what's coming", "forecast", "what lies ahead", "what to expect",
    "upcoming period", "this year", "rest of the year",
]

TIMING_TRIGGERS = [
    "when will", "when can", "when would", "how long",
    "which year", "which month", "will i ever", "will i get",
    "will i find", "will i have", "when do i",
    # "will we ..." / "will my ..." questions were falling through to thematic, so a
    # plainly predictive query ("will my marriage work out?") lost its predictive
    # intent — no dasha mechanism, no future-tense check, no timing windows.
    "will we", "will my", "will there be", "am i going to", "how soon",
]

MIXED_INDICATORS = [
    " and when", "when will i get", "what kind of", "how will my",
    "what type of", "what will my", "will i and when",
]

AFFIRMATION_PATTERNS = [
    "yes", "ok", "okay", "sure", "go on", "tell me more",
    "elaborate", "continue", "and?", "so?", "explain", "how so",
    "please", "go ahead",
]

DOMAIN_KEYWORDS = {
    "career": ["job", "career", "promotion", "boss", "work", "office", "profession",
               "employment", "salary", "colleague", "workplace", "role", "senior role",
               "manager", "resign", "quit", "appraisal", "interview", "business"],
    "relationship": ["relationship", "marriage", "married", "marry", "wedding", "partner",
                     "husband", "wife", "love", "dating", "divorce", "spouse", "attract",
                     "attracting", "romance", "in-laws", "marriage life"],
    "wealth": ["money", "wealth", "income", "savings", "financial", "rich", "earn", "cash",
               "funds", "profit", "investment", "stocks", "crypto"],
    "health": ["health", "illness", "disease", "body", "energy", "vitality", "sick",
               "medical", "doctor", "fitness", "anxiety"],
    "property": ["property", "house", "home", "real estate", "land", "flat", "apartment",
                 "buy home", "rent"],
    "children": ["child", "children", "baby", "babies", "pregnancy", "pregnant", "fertility",
                 "son", "daughter", "kids", "conceive", "conceiving"],
    "spirituality": ["spiritual", "dharma", "meditation", "karma", "faith", "meaning",
                     "purpose", "guru", "sadhana"],
    "travel": ["travel", "relocate", "relocating", "abroad", "foreign", "move", "moving",
               "visa", "immigration", "overseas", "relocation", "settle abroad"],
    "fame": ["fame", "famous", "social media", "audience", "followers", "recognition",
             "public", "viral", "reputation"],
}


# Precompiled word-boundary matchers, one per (domain, keyword). Common inflections
# are matched off the stem, so "colleague" still catches "colleagues" and "earn"
# catches "earning" — plain \b anchoring alone silently dropped every plural, which
# sent "how do my colleagues see me?" to the general slice instead of career.
# Stems that change shape ("move" → "moving") are listed explicitly above.
_INFLECTIONS = r"(?:s|es|ed|ing|d|r|rs)?"
_KEYWORD_RES = {
    domain: [(kw, re.compile(rf"\b{re.escape(kw)}{_INFLECTIONS}\b")) for kw in keywords]
    for domain, keywords in DOMAIN_KEYWORDS.items()
}


def domain_scores(message: str):
    """{domain: (hits, longest_matched_keyword_length)} for a message.

    The second element breaks ties by specificity. Without it, "will my marriage work
    out?" scored relationship=1 (marriage) and career=1 (work) and the tie fell to
    dict order — career — so 7th-house questions were read from the 10th-house slice.
    A longer keyword is the more specific signal: "marriage" beats "work"."""
    msg = message.lower()
    scores = {}
    for domain, patterns in _KEYWORD_RES.items():
        matched = [kw for kw, rx in patterns if rx.search(msg)]
        scores[domain] = (len(matched), max((len(kw) for kw in matched), default=0))
    return scores


def _ranked_domains(message: str):
    return sorted(domain_scores(message).items(), key=lambda kv: kv[1], reverse=True)


def _has_dominant_domain(message: str) -> bool:
    """True when the message names a specific life domain."""
    return _ranked_domains(message)[0][1][0] > 0


def classify_query_type(message: str) -> str:
    msg = message.lower().strip()
    if len(msg.split()) <= 5 and any(p in msg for p in AFFIRMATION_PATTERNS):
        return "affirmation"

    forecast_hit = any(t in msg for t in FORECAST_TRIGGERS)
    has_timing = any(t in msg for t in TIMING_TRIGGERS)
    has_mixed = any(m in msg for m in MIXED_INDICATORS)

    # A forecast trigger only means "forecast" when the question is open-ended.
    # "Will I get a promotion at work this year?" used to route to forecast mode,
    # which forced the generic forecast chart slice and wrote the turn to the
    # forecast ledger — the career question never reached the career reading.
    # A dated question about ONE named domain is a timing/mixed question instead.
    if forecast_hit and not _has_dominant_domain(message):
        return "forecast"
    if has_timing and has_mixed:
        return "mixed"
    if has_timing:
        return "timing"
    if forecast_hit:
        return "mixed"      # domain-specific, but explicitly dated → what + when
    return "thematic"


def classify_domain(message: str):
    if classify_query_type(message) == "forecast":
        return ["forecast"]
    ranked = _ranked_domains(message)
    (top_domain, (top_hits, top_len)), (second_domain, (second_hits, second_len)) = ranked[0], ranked[1]
    if top_hits == 0:
        return ["general"]
    if second_hits == 0 or (top_hits - second_hits) > 1:
        return [top_domain]
    # Equal hit counts but a far less specific keyword means the second domain was
    # matched incidentally ("work" in "will my marriage work out?"). Treating that as
    # a real secondary domain merges a chart slice the question never asked for and
    # writes the reading into that domain's ledger, corrupting its rotation.
    if top_hits == second_hits and (top_len - second_len) > 3:
        return [top_domain]
    return [top_domain, second_domain]
