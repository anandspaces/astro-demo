"""Domain and query-type classification (Part 9)."""

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
               "employment", "salary", "colleague", "workplace"],
    "relationship": ["relationship", "marriage", "partner", "husband", "wife", "love",
                     "dating", "divorce", "spouse", "attract", "romance", "in-laws", "marriage life"],
    "wealth": ["money", "wealth", "income", "savings", "financial", "rich", "earn", "cash",
               "funds", "profit", "investment", "stocks", "crypto"],
    "health": ["health", "illness", "disease", "body", "energy", "vitality", "sick",
               "medical", "doctor", "fitness", "anxiety"],
    "property": ["property", "house", "home", "real estate", "land", "flat", "apartment",
                 "buy home", "rent"],
    "children": ["child", "children", "baby", "pregnancy", "fertility", "son", "daughter",
                 "kids", "conceive"],
    "spirituality": ["spiritual", "dharma", "meditation", "karma", "faith", "meaning",
                     "purpose", "guru", "sadhana"],
    "travel": ["travel", "relocate", "abroad", "foreign", "move", "visa", "immigration",
               "overseas", "relocation"],
    "fame": ["fame", "famous", "social media", "audience", "followers", "recognition",
             "public", "viral", "reputation"],
}


def classify_query_type(message: str) -> str:
    msg = message.lower().strip()
    if len(msg.split()) <= 5 and any(p in msg for p in AFFIRMATION_PATTERNS):
        return "affirmation"
    if any(t in msg for t in FORECAST_TRIGGERS):
        return "forecast"
    has_timing = any(t in msg for t in TIMING_TRIGGERS)
    has_mixed = any(m in msg for m in MIXED_INDICATORS)
    if has_timing and has_mixed:
        return "mixed"
    if has_timing:
        return "timing"
    return "thematic"


def classify_domain(message: str):
    if classify_query_type(message) == "forecast":
        return ["forecast"]
    msg = message.lower()
    scores = {d: 0 for d in DOMAIN_KEYWORDS}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in msg:
                scores[domain] += 1
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top, second = ranked[0], ranked[1]
    if top[1] > 0 and second[1] > 0 and (top[1] - second[1]) <= 1:
        return [top[0], second[0]]
    return [top[0]] if top[1] > 0 else ["general"]
