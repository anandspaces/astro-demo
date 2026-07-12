"""Datastore repository (Part 7), on SQLAlchemy ORM. Backend-agnostic (Postgres or
SQLite) via db/database.py. Schema is defined in db/models.py; migrations in db/alembic.

Public functions keep returning plain dicts/values so the pipeline layer is unchanged.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select

from .database import Session, backend_name, target  # noqa: F401  (re-exported)
from .models import SessionMessage, User, UserChart, UserReadingLedger, UserSession

SESSION_TIMEOUT_MIN = 30


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
    """Fetch a session; reset state if idle > 30 min. Never touches ledger/messages."""
    with Session.begin() as s:
        row = s.get(UserSession, session_id)
        if row is None:
            row = UserSession(session_id=session_id, user_id=user_id, interaction_count=0,
                              last_active=now(), created_at=now())
            s.add(row)
        else:
            idle_min = (now() - row.last_active).total_seconds() / 60
            if idle_min > SESSION_TIMEOUT_MIN:
                row.last_mechanism = row.last_domain = row.last_insight_axis = None
                row.interaction_count = 0
                row.last_active = now()
        return _row(row, "session_id", "user_id", "last_mechanism", "last_domain",
                    "last_insight_axis", "interaction_count", "last_active")


def get_session_state(session_id):
    with Session() as s:
        row = s.get(UserSession, session_id)
        return _row(row, "session_id", "user_id", "last_mechanism", "last_domain",
                    "last_insight_axis", "interaction_count") or {}


def update_session_state(session_id, planner_json):
    with Session.begin() as s:
        row = s.get(UserSession, session_id)
        if row:
            row.last_mechanism = planner_json.get("mechanism")
            row.last_domain = planner_json.get("domain")
            row.last_insight_axis = planner_json.get("insight_axis")
            row.last_active = now()


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
def save_turn(session_id, user_id, role, content, domain=None, mechanism=None, query_type=None):
    with Session.begin() as s:
        s.add(SessionMessage(id=generate_id(), session_id=session_id, user_id=user_id, role=role,
                             content=content, domain=domain, mechanism_used=mechanism,
                             query_type=query_type, created_at=now()))


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


# Back-compat for callers that referenced store.DB_PATH.
DB_PATH = target()
