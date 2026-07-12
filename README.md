# StarSage — Vedic Astrology Engine + AI Reading Pipeline

StarSage computes a person's Vedic birth chart with professional-grade astronomy, then
answers their life questions with AI readings grounded in *that* chart — not generic
horoscopes. It's a full implementation of the 18-part StarSage spec.

- **Chart engine** — deterministic astronomy (Swiss Ephemeris): planets, houses, nakshatras,
  Vimshottari dashas with exact dates, divisional charts, yogas, transits.
- **AI pipeline** — every question runs **Classify → Plan → Generate → Critique**, with a
  memory ledger that stops it repeating itself across a conversation.
- **Provider-flexible** — the AI runs on **Claude, GPT, or Gemini** (or an offline mock),
  switched by one setting.

> Spec, annotated with the 23 bugs found and fixed: [docs/research/01-chart-engine.md](docs/research/01-chart-engine.md)
> · Handover + live samples: [docs/HANDOVER.md](docs/HANDOVER.md) · Demo script: [docs/DEMO.md](docs/DEMO.md)

## Layout

```
src/astro/      Chart calculation engine — zero LLM dependency
src/pipeline/   Classify → Plan → Generate → Critique → Ledger
src/db/         SQLAlchemy models + Alembic migrations + repository + memory ledger
src/jobs/       Daily transit recalc + prediction surfacing
src/server.py   HTTP server wrapping the pipeline
src/main.py     CLI: init / migrate / signup / chart / chat
src/tests/      Engine sanity tests
web/            Browser test console (streaming)
```

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # then edit (see Configuration)
```

## Configuration

All config lives in `.env` (auto-loaded). Nothing is required — with no keys it runs in
offline **mock** mode.

```bash
# LLM provider: claude | gpt | gemini | mock  (unset = auto-detect from keys, else mock)
STARSAGE_PROVIDER=gemini
GEMINI_API_KEY=...            # or ANTHROPIC_API_KEY / OPENAI_API_KEY

# Datastore: PostgreSQL (required) — any standard Postgres URL
DATABASE_URL=postgresql://postgres:root@127.0.0.1:5432/starsage
```

## Quick start

```bash
python src/main.py migrate                                   # create schema
python src/main.py signup --name "Asha" --dob 1992-06-20 --tob 14:15 \
    --pob "Mumbai, India" --tz Asia/Kolkata              # prints a user_id
python src/main.py chart --user <user_id>                    # full natal chart JSON
python src/main.py chat  --user <user_id> --message "When will my career take off?"
```

## Web console

A browser UI that streams the reading live (stage-by-stage: Reading → Planning → Writing →
Reviewing) with a provider dropdown.

```bash
python src/server.py            # -> http://localhost:8765
```

## Database & migrations

The stack is **SQLAlchemy** (typed schema) + **Alembic** (migrations) on **PostgreSQL**, set
via `DATABASE_URL` — any standard host (local, Docker, Cloud SQL, RDS, Neon, Supabase…). JSON
columns are real `jsonb`.

The schema lives in `src/db/models.py` (one place). Alembic autogenerates migrations from it
and tracks the applied revision in an `alembic_version` table.

```bash
python src/main.py migrate            # apply pending migrations (alembic upgrade head)
python src/main.py migrate --status   # current vs head revision

# after changing db/models.py, generate a new migration:
python -m alembic -c alembic.ini revision --autogenerate -m "describe change"
python src/main.py migrate
```

## Provider switch

If `STARSAGE_PROVIDER` is unset, it auto-detects from whichever key is present
(claude > gpt > gemini), falling back to `mock`. Model tiers (override any via env, e.g.
`STARSAGE_GEMINI_QUALITY=gemini-3.1-pro-preview`):

| Tier | Used by | claude | gpt | gemini |
|------|---------|--------|-----|--------|
| quality | Generator, Synthesis | `claude-sonnet-5` | `gpt-4o` | `gemini-2.5-pro` |
| fast | Planner, Critic | `claude-haiku-4-5` | `gpt-4o-mini` | `gemini-2.5-flash` |

## Scheduled jobs

```bash
python src/jobs/recalc_transits.py       # daily: refresh each chart's transit block
python src/jobs/surface_predictions.py   # daily: push when a prediction window goes active
```

Wire into cron. Push delivery is a stub until a provider (FCM/APNs/web-push) is chosen.

## Testing

```bash
python src/tests/test_engine.py          # engine sanity checks
python src/scripts/test_apis.py          # probe configured LLM providers + one live turn
python src/scripts/demo_run.py           # generate sample readings for several users
```

## Design decisions (spec left these open)

- **Datastore** — PostgreSQL via `DATABASE_URL`, behind one repository API (`src/db/store.py`).
- **Critic** — synchronous, fronted by a deterministic pre-check gate
  (`pipeline/precheck.py`) for the checkable criteria (word count, hook length, tense, yoga
  reuse); the LLM Critic handles judgment calls. The streaming path (`pipeline/stream.py`)
  uses the async model: stream first, critique after.
- **`STARSAGE_SYSTEM_PROMPT`** — not in the spec; authored in `pipeline/prompts.py` with the
  four response structures. Replaceable placeholder.
- **`fame` domain** — promoted to a first-class domain with its own checklist.
- **Timing windows** — the Planner emits structured `{label, start, end}` so dates are never
  parsed from free text.

## Not yet accuracy-validated

The engine passes internal-consistency tests only. Before production, validate ≥5 charts
against **Jagannatha Hora** (ascendant, planetary houses, nakshatras, MD/AD/PD dates) per the
spec's mandatory step. Divisional charts (D2/D4/D7) are the most error-prone — verify first.
