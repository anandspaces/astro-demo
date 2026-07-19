"""Domain / query-type classifier, tested in isolation (no LLM, no DB).

Runs a fixed set of queries through classify.py alone and prints the raw output
plus the per-domain keyword scores, so a misrouted query can be traced to the
keyword that caused it. Each case carries the domain it should produce; the exit
code is non-zero if any case fails, so this can gate a deploy.

    python -m scripts.test_classifier        (from src/)
"""
import sys

from pipeline.classify import (DOMAIN_KEYWORDS, classify_domain,
                               classify_query_type, domain_scores)

# (query, expected primary domain, expected query type). `domains` is checked on the
# primary only, except where a case is listed in MULTI_DOMAIN below.
CASES = [
    ("Will my marriage work out?",                    "relationship", "timing"),
    ("When will I get married?",                      "relationship", "mixed"),
    ("Is my husband's work affecting our marriage?",  "relationship", "thematic"),
    ("Why do I keep attracting the same partner?",    "relationship", "thematic"),
    ("Will I get a promotion at work this year?",     "career",       "timing"),
    ("My boss keeps overlooking me for the job",      "career",       "thematic"),
    ("How do my colleagues actually see me?",         "career",       "thematic"),
    ("Will I get a senior role, and when?",           "career",       "mixed"),
    ("How do I earn more money?",                     "wealth",       "thematic"),
    ("Should I buy a house next year?",               "property",     "mixed"),
    ("My anxiety has been draining my energy",        "health",       "thematic"),
    ("When can I move abroad?",                       "travel",       "timing"),
    ("Will we be able to conceive a child?",          "children",     "timing"),
    ("What is my life purpose?",                      "spirituality", "thematic"),
    ("How will my year ahead look?",                  "forecast",     "forecast"),
    ("Tell me more",                                  None,           "affirmation"),
]

# Exact expected domain list, for the cases where the secondary domain matters.
MULTI_DOMAIN = {
    # genuinely two-domain: career is named in its own right, not incidentally
    "Is my husband's work affecting our marriage?": ["relationship", "career"],
    # "work" here is idiomatic ("work out"), not a career question
    "Will my marriage work out?": ["relationship"],
}


def main():
    failures = []
    print(f"{'query':<48} {'domains':<28} {'query_type':<12} verdict")
    print("-" * 100)
    for query, want_domain, want_qt in CASES:
        qt = classify_query_type(query)
        domains = classify_domain(query)
        primary = domains[0]
        ok_domain = want_domain is None or primary == want_domain
        if query in MULTI_DOMAIN:
            ok_domain = ok_domain and domains == MULTI_DOMAIN[query]
        ok_qt = qt == want_qt
        verdict = "ok" if (ok_domain and ok_qt) else "FAIL"
        if verdict == "FAIL":
            failures.append((query, primary, want_domain, qt, want_qt))
        print(f"{query:<48} {str(domains):<28} {qt:<12} {verdict}")
        if verdict == "FAIL":
            scored = {d: s for d, s in domain_scores(query).items() if s}
            print(f"{'':<48} scores={scored}  "
                  f"expected domain={want_domain} query_type={want_qt}")

    print("-" * 100)
    if failures:
        print(f"{len(failures)} of {len(CASES)} cases FAILED:")
        for query, got_d, want_d, got_q, want_q in failures:
            print(f"  {query!r}: domain {got_d} (want {want_d}), query_type {got_q} (want {want_q})")
    else:
        print(f"all {len(CASES)} cases passed")

    # A relationship query classified as career is the specific regression that sent
    # 7th-house questions into the 10th-house chart slice — call it out explicitly.
    misrouted = [q for q, got_d, want_d, *_ in failures if want_d == "relationship" and got_d == "career"]
    if misrouted:
        print(f"\nCRITICAL: {len(misrouted)} relationship quer(y/ies) classified as career: {misrouted}")

    print(f"\ndomains configured: {', '.join(sorted(DOMAIN_KEYWORDS))}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
