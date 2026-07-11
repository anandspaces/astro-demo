"""SQLite datastore (Part 7) behind a small repository API.

JSONB in the spec -> JSON stored as TEXT here (dev-friendly, zero setup).
Swap this module for a Postgres implementation without touching callers.
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

DB_PATH = os.environ.get("STARSAGE_DB", os.path.join(os.path.dirname(__file__), "starsage.db"))

SESSION_TIMEOUT_MIN = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY, name TEXT, dob TEXT, tob TEXT, pob TEXT,
    timezone TEXT, lat REAL, lon REAL, created_at TEXT
);
CREATE TABLE IF NOT EXISTS user_charts (
    user_id TEXT PRIMARY KEY, chart_json TEXT, calculated_at TEXT
);
CREATE TABLE IF NOT EXISTS user_reading_ledger (
    user_id TEXT, domain TEXT, ledger_json TEXT, last_updated TEXT,
    PRIMARY KEY (user_id, domain)
);
CREATE TABLE IF NOT EXISTS user_sessions (
    session_id TEXT PRIMARY KEY, user_id TEXT, last_mechanism TEXT, last_domain TEXT,
    last_insight_axis TEXT, interaction_count INTEGER DEFAULT 0,
    last_active TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS session_messages (
    id TEXT PRIMARY KEY, session_id TEXT, user_id TEXT, role TEXT, content TEXT,
    domain TEXT, mechanism_used TEXT, query_type TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_msgs ON session_messages (session_id, created_at);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def today():
    return datetime.now(timezone.utc).date().isoformat()


def generate_id():
    return uuid.uuid4().hex


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.executescript(SCHEMA)


# ---- users & charts -------------------------------------------------------
def create_user(name, dob, tob, pob, timezone_, lat=None, lon=None):
    uid = generate_id()
    with _conn() as c:
        c.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?)",
            (uid, name, dob, tob, pob, timezone_, lat, lon, now_iso()),
        )
    return uid


def get_user(user_id):
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def save_chart(user_id, chart):
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO user_charts VALUES (?,?,?)",
            (user_id, json.dumps(chart), now_iso()),
        )


def get_user_chart(user_id):
    with _conn() as c:
        row = c.execute("SELECT chart_json FROM user_charts WHERE user_id=?", (user_id,)).fetchone()
    return json.loads(row["chart_json"]) if row else None


# ---- ledger ---------------------------------------------------------------
def get_ledger_from_db(user_id, domain):
    with _conn() as c:
        row = c.execute(
            "SELECT ledger_json FROM user_reading_ledger WHERE user_id=? AND domain=?",
            (user_id, domain),
        ).fetchone()
    return json.loads(row["ledger_json"]) if row else None


def save_ledger(user_id, domain, ledger):
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO user_reading_ledger VALUES (?,?,?,?)",
            (user_id, domain, json.dumps(ledger), now_iso()),
        )


def get_all_domain_ledgers(user_id):
    with _conn() as c:
        rows = c.execute(
            "SELECT domain, ledger_json FROM user_reading_ledger WHERE user_id=?", (user_id,)
        ).fetchall()
    return {r["domain"]: json.loads(r["ledger_json"]) for r in rows}


# ---- sessions -------------------------------------------------------------
def get_or_create_session(session_id, user_id):
    """Fetch a session; reset state if idle > 30 min. Never touches ledger/messages."""
    with _conn() as c:
        row = c.execute("SELECT * FROM user_sessions WHERE session_id=?", (session_id,)).fetchone()
        if row:
            last = datetime.fromisoformat(row["last_active"])
            idle_min = (datetime.now(timezone.utc) - last).total_seconds() / 60
            if idle_min > SESSION_TIMEOUT_MIN:
                c.execute(
                    "UPDATE user_sessions SET last_mechanism=NULL, last_domain=NULL, "
                    "last_insight_axis=NULL, interaction_count=0, last_active=? WHERE session_id=?",
                    (now_iso(), session_id),
                )
                row = c.execute("SELECT * FROM user_sessions WHERE session_id=?", (session_id,)).fetchone()
            return dict(row)
        c.execute(
            "INSERT INTO user_sessions VALUES (?,?,?,?,?,?,?,?)",
            (session_id, user_id, None, None, None, 0, now_iso(), now_iso()),
        )
        row = c.execute("SELECT * FROM user_sessions WHERE session_id=?", (session_id,)).fetchone()
    return dict(row)


def get_session_state(session_id):
    with _conn() as c:
        row = c.execute("SELECT * FROM user_sessions WHERE session_id=?", (session_id,)).fetchone()
    return dict(row) if row else {}


def update_session_state(session_id, planner_json):
    with _conn() as c:
        c.execute(
            "UPDATE user_sessions SET last_mechanism=?, last_domain=?, last_insight_axis=?, "
            "last_active=? WHERE session_id=?",
            (planner_json.get("mechanism"), planner_json.get("domain"),
             planner_json.get("insight_axis"), now_iso(), session_id),
        )


def get_interaction_count(session_id):
    with _conn() as c:
        row = c.execute(
            "SELECT interaction_count FROM user_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
    return row["interaction_count"] if row else 0


def increment_interaction_count(session_id):
    with _conn() as c:
        c.execute(
            "UPDATE user_sessions SET interaction_count=interaction_count+1, last_active=? "
            "WHERE session_id=?",
            (now_iso(), session_id),
        )


# ---- messages -------------------------------------------------------------
def save_turn(session_id, user_id, role, content, domain=None, mechanism=None, query_type=None):
    with _conn() as c:
        c.execute(
            "INSERT INTO session_messages VALUES (?,?,?,?,?,?,?,?,?)",
            (generate_id(), session_id, user_id, role, content, domain, mechanism, query_type, now_iso()),
        )


def get_session_messages(session_id):
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content FROM session_messages WHERE session_id=? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_recent_history(session_id, limit=6):
    return get_session_messages(session_id)[-limit:]


def get_last_assistant_turn(session_id):
    with _conn() as c:
        row = c.execute(
            "SELECT content FROM session_messages WHERE session_id=? AND role='assistant' "
            "ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    return row["content"] if row else ""
