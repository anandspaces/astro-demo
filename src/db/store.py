"""Datastore repository (Part 7), on SQLAlchemy ORM over PostgreSQL (db/database.py).
Schema is defined in db/models.py; migrations in db/alembic.

Public functions keep returning plain dicts/values so the pipeline layer is unchanged.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select

from .database import Session, backend_name, target  # noqa: F401  (re-exported)
from .models import (AppSettings, PromptOverride, SessionMessage, User,
                     UserChart, UserReadingLedger, UserSession)

SETTINGS_ID = "global"   # singleton row until per-account auth lands

log = logging.getLogger("starsage.store")

# How many recent assistant turns get_session_state scans for rotation state. Each
# field takes its most recent non-null value, so a turn that doesn't set one (an
# affirmation carries no mechanism) doesn't erase rotation for the next turn.
ROTATION_LOOKBACK = 10


def now():
    return datetime.now(timezone.utc)


def now_iso():
    return now().isoformat()


def today():
    return now().date().isoformat()


def generate_id():
    return uuid.uuid4().hex


def init_db():
    """Ensure the schema is up to date by applying Alembic migrations."""
    from . import migrate
    return migrate.upgrade()


def _row(obj, *cols):
    return {c: getattr(obj, c) for c in cols} if obj else None


# ---- app settings (provider + encrypted keys + chosen model) --------------
def get_settings():
    """Return the singleton settings row as a dict (empty dict if unset)."""
    with Session() as s:
        return _row(s.get(AppSettings, SETTINGS_ID), "provider",
                    "claude_key_enc", "gpt_key_enc", "gemini_key_enc",
                    "claude_model", "gpt_model", "gemini_model", "updated_at") or {}


def save_settings(provider=None, key_enc_by_provider=None, model_by_provider=None):
    """Upsert settings. `provider` sets the active provider when given (not None);
    each entry in `key_enc_by_provider` ({provider: enc_or_None}) overwrites that
    provider's stored key (None clears it; an absent provider is left unchanged);
    `model_by_provider` ({provider: model_id_or_None}) sets the chosen model."""
    key_col = {"claude": "claude_key_enc", "gpt": "gpt_key_enc", "gemini": "gemini_key_enc"}
    model_col = {"claude": "claude_model", "gpt": "gpt_model", "gemini": "gemini_model"}
    with Session.begin() as s:
        row = s.get(AppSettings, SETTINGS_ID)
        if row is None:
            row = AppSettings(id=SETTINGS_ID)
            s.add(row)
        if provider is not None:
            row.provider = provider
        for prov, enc in (key_enc_by_provider or {}).items():
            if prov in key_col:
                setattr(row, key_col[prov], enc)
        for prov, model in (model_by_provider or {}).items():
            if prov in model_col:
                setattr(row, model_col[prov], model or None)
        row.updated_at = now()


# ---- prompt overrides -----------------------------------------------------
def get_prompt_override(name):
    """Return the override content for a prompt name, or None if not overridden."""
    with Session() as s:
        row = s.get(PromptOverride, name)
        return row.content if row else None


def get_all_prompt_overrides():
    """Map {name: content} of every prompt currently overridden."""
    with Session() as s:
        return {r.name: r.content for r in s.execute(select(PromptOverride)).scalars()}


def save_prompt_override(name, content):
    with Session.begin() as s:
        s.merge(PromptOverride(name=name, content=content, updated_at=now()))


def delete_prompt_override(name):
    """Remove an override so the prompt reverts to its hardcoded default. Returns
    True if a row was deleted."""
    with Session.begin() as s:
        row = s.get(PromptOverride, name)
        if not row:
            return False
        s.delete(row)
        return True


# ---- users & charts -------------------------------------------------------
def create_user(name, dob, tob, pob, timezone_, lat=None, lon=None):
    uid = generate_id()
    with Session.begin() as s:
        s.add(User(user_id=uid, name=name, dob=dob, tob=tob, pob=pob,
                   timezone=timezone_, lat=lat, lon=lon, created_at=now()))
    return uid


def get_user(user_id):
    with Session() as s:
        u = s.get(User, user_id)
        return _row(u, "user_id", "name", "dob", "tob", "pob", "timezone", "lat", "lon", "created_at")


def save_chart(user_id, chart):
    with Session.begin() as s:
        s.merge(UserChart(user_id=user_id, chart_json=chart, calculated_at=now()))


def get_user_chart(user_id):
    with Session() as s:
        row = s.get(UserChart, user_id)
        return row.chart_json if row else None


# ---- ledger ---------------------------------------------------------------
def get_ledger_from_db(user_id, domain):
    with Session() as s:
        row = s.get(UserReadingLedger, (user_id, domain))
        return row.ledger_json if row else None


def save_ledger(user_id, domain, ledger):
    with Session.begin() as s:
        s.merge(UserReadingLedger(user_id=user_id, domain=domain, ledger_json=ledger, last_updated=now()))


def get_all_domain_ledgers(user_id):
    with Session() as s:
        rows = s.execute(select(UserReadingLedger).where(UserReadingLedger.user_id == user_id)).scalars()
        return {r.domain: r.ledger_json for r in rows}


# ---- sessions -------------------------------------------------------------
def get_or_create_session(session_id, user_id):
    """Fetch a session, creating it if absent. Never touches ledger/messages.

    No idle expiry (removed 2026-07): a 30-minute reset wiped interaction_count and
    rotation state, so a returning user restarted the synthesis cycle and could be
    served the same mechanism/axis they just had. A session is a durable thread."""
    with Session.begin() as s:
        row = s.get(UserSession, session_id)
        if row is None:
            row = UserSession(session_id=session_id, user_id=user_id, interaction_count=0,
                              last_active=now(), created_at=now())
            s.add(row)
        else:
            row.last_active = now()
        return _row(row, "session_id", "user_id", "last_mechanism", "last_domain",
                    "last_insight_axis", "interaction_count", "last_active")


_ROTATION_COLUMNS = {
    "last_mechanism": SessionMessage.mechanism_used,
    "last_domain": SessionMessage.domain,
    "last_insight_axis": SessionMessage.insight_axis,
    "last_closing_type": SessionMessage.closing_type_used,
}


def get_session_state(session_id):
    """Rotation state for the next Planner/Generator turn.

    Read from the actual conversation (`session_messages`) rather than a mirrored
    session row, so what the Planner is told to rotate away from is exactly what was
    last written. Each field takes the most recent assistant turn that set it.
    interaction_count stays on `user_sessions` — it is a durable tally, not rotation
    state. Any failure here degrades to an empty state (fresh rotation) and is logged
    loudly: silently returning stale/empty state corrupts every following turn."""
    state = {}
    try:
        with Session() as s:
            rows = s.execute(
                select(SessionMessage.mechanism_used, SessionMessage.domain,
                       SessionMessage.insight_axis, SessionMessage.closing_type_used)
                .where(SessionMessage.session_id == session_id,
                       SessionMessage.role == "assistant")
                .order_by(SessionMessage.created_at.desc())
                .limit(ROTATION_LOOKBACK)
            ).all()
            for key, col in _ROTATION_COLUMNS.items():
                state[key] = next((v for v in (getattr(r, col.key) for r in rows) if v), None)
            session_row = s.get(UserSession, session_id)
            if session_row:
                state["session_id"] = session_row.session_id
                state["user_id"] = session_row.user_id
                state["interaction_count"] = session_row.interaction_count
                # Pre-F2 sessions have no per-message rotation columns; fall back to
                # the mirrored session row so rotation survives the migration.
                for key in ("last_mechanism", "last_domain", "last_insight_axis"):
                    if state.get(key) is None:
                        state[key] = getattr(session_row, key)
    except Exception as e:
        log.error("get_session_state FAILED for session=%s: %s: %s — rotation state lost "
                  "for this turn", session_id, type(e).__name__, e, exc_info=True)
        return {}
    return state


def update_session_state(session_id, planner_json):
    """Persist last_mechanism/domain/insight_axis for the session. Returns True on a
    real write, False if the session row is missing (a silent no-op the caller must
    log — a dropped write here breaks mechanism rotation on every later turn)."""
    with Session.begin() as s:
        row = s.get(UserSession, session_id)
        if not row:
            return False
        row.last_mechanism = planner_json.get("mechanism")
        row.last_domain = planner_json.get("domain")
        row.last_insight_axis = planner_json.get("insight_axis")
        row.last_active = now()
        return True


def get_interaction_count(session_id):
    with Session() as s:
        row = s.get(UserSession, session_id)
        return row.interaction_count if row else 0


def increment_interaction_count(session_id):
    with Session.begin() as s:
        row = s.get(UserSession, session_id)
        if row:
            row.interaction_count = (row.interaction_count or 0) + 1
            row.last_active = now()


# ---- messages -------------------------------------------------------------
def save_turn(session_id, user_id, role, content, domain=None, mechanism=None, query_type=None,
              insight_axis=None, closing_type=None):
    """Persist one turn. On assistant turns pass the plan's mechanism/insight_axis/
    closing_type — get_session_state reads rotation back out of these columns."""
    with Session.begin() as s:
        s.add(SessionMessage(id=generate_id(), session_id=session_id, user_id=user_id, role=role,
                             content=content, domain=domain, mechanism_used=mechanism,
                             query_type=query_type, insight_axis=insight_axis,
                             closing_type_used=closing_type, created_at=now()))


def get_session_messages(session_id):
    with Session() as s:
        rows = s.execute(
            select(SessionMessage.role, SessionMessage.content)
            .where(SessionMessage.session_id == session_id)
            .order_by(SessionMessage.created_at.asc())
        ).all()
    return [{"role": r.role, "content": r.content} for r in rows]


def get_recent_history(session_id, limit=6):
    return get_session_messages(session_id)[-limit:]


def get_last_assistant_turn(session_id):
    with Session() as s:
        row = s.execute(
            select(SessionMessage.content)
            .where(SessionMessage.session_id == session_id, SessionMessage.role == "assistant")
            .order_by(SessionMessage.created_at.desc()).limit(1)
        ).first()
    return row.content if row else ""


# ---- batch/cron helpers ---------------------------------------------------
def all_chart_user_ids():
    """Every user_id that has a stored chart (for daily transit recalc)."""
    with Session() as s:
        return [r[0] for r in s.execute(select(UserChart.user_id)).all()]


def all_ledger_keys():
    """Every (user_id, domain) pair in the reading ledger (for prediction surfacing)."""
    with Session() as s:
        return [(r.user_id, r.domain) for r in
                s.execute(select(UserReadingLedger.user_id, UserReadingLedger.domain)).all()]
