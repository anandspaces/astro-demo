# StarSage — Vedic Astrology Engine + AI Reading Pipeline

Full implementation of the 18-part StarSage spec (see
[docs/research/01-chart-engine.md](docs/research/01-chart-engine.md) for the
annotated spec and the 23 flagged bugs, all fixed in this build).

## Layout

```
src/astro/      Chart engine (Week 1) — zero LLM dependency
src/pipeline/   Classify → Plan → Generate → Critique → Ledger (Week 2)
db/             SQLite datastore + memory ledger (Part 7-8)
jobs/           Daily transit recalc + prediction surfacing (Part 17)
main.py         CLI: init / signup / chart / chat
tests/          Engine sanity tests
```

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt   # pyswisseph+pytz required; LLM SDKs optional
```

## Quick start

```bash
python main.py init
python main.py signup --name "Asha" --dob 1992-06-20 --tob 14:15 \
    --pob "Mumbai, India" --tz Asia/Kolkata
# -> prints a user_id
python main.py chat --user <user_id> --message "When will I get a promotion?"
python main.py chart --user <user_id>        # dump the full natal chart JSON
```

## LLM provider switch

Runs in **mock mode** by default (deterministic, no network, no keys) so the whole
pipeline is testable offline. Pick a real provider with one env var:

```bash
export STARSAGE_PROVIDER=claude   # or: gpt | gemini
export ANTHROPIC_API_KEY=...      # claude
export OPENAI_API_KEY=...         # gpt
export GEMINI_API_KEY=...         # gemini
```

If `STARSAGE_PROVIDER` is unset, the provider is auto-detected from whichever key
is present (claude > gpt > gemini), falling back to `mock`.

Model tiers (override any via env):

| Tier | Used by | claude | gpt | gemini |
|------|---------|--------|-----|--------|
| quality | Generator, Synthesis | `claude-sonnet-5` | `gpt-4o` | `gemini-2.5-pro` |
| fast | Planner, Critic | `claude-haiku-4-5` | `gpt-4o-mini` | `gemini-2.5-flash` |

Override e.g. `STARSAGE_CLAUDE_QUALITY=claude-opus-4-8`.

## Scheduled jobs

```bash
python jobs/recalc_transits.py       # daily: refresh each chart's transit block
python jobs/surface_predictions.py   # daily: push when a prediction window goes active
```

Wire into cron; push delivery is a stub until a provider (FCM/APNs/web-push) is chosen.

## Decisions taken (spec left these open)

- **Datastore:** SQLite (stdlib, zero-setup) behind a repository API in `db/store.py`.
  JSONB → JSON-as-TEXT. Swap the module for Postgres without touching callers.
- **Critic:** synchronous + a deterministic pre-check gate (`pipeline/precheck.py`)
  for the checkable Part-13 criteria (word count, hook length, tense, yoga reuse),
  reserving the LLM Critic for judgment calls. This reconciles Parts 10/13 (blocking)
  with Part 16 (async) — flip to fully async later by moving the Critic off the
  response path in `modes._generate_and_finalise`.
- **`STARSAGE_SYSTEM_PROMPT`** (not in the spec): authored in `pipeline/prompts.py`
  with the four response structures. Marked as a replaceable placeholder.
- **`fame` domain:** promoted to a real domain with its own checklist.
- **Timing windows:** the Planner emits structured `{label,start,end}` so
  `parse_window_dates` never parses free text (spec bug #23).

## Not yet accuracy-validated

The engine passes internal-consistency tests only. Before production, validate ≥5
charts against **Jagannatha Hora** — ascendant, planetary houses, nakshatras, and
MD/AD/PD dates — per the spec's mandatory validation step. Divisional charts
(D2/D4/D7 especially) are the most error-prone; verify those first.
```
