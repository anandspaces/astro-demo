"""SQLAlchemy engine + session, resolved from DATABASE_URL (PostgreSQL only —
any host: local, Docker, Cloud SQL, RDS, Neon, Supabase). SQLAlchemy manages the
connection pool.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def _resolve_url() -> str:
    raw = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("STARSAGE_DATABASE_URL")
        or os.environ.get("SUPABASE_DB_URL")
        or ""
    ).strip()
    if not raw:
        raise RuntimeError(
            "DATABASE_URL is not set. StarSage requires PostgreSQL — set e.g. "
            "DATABASE_URL=postgresql://user:pw@host:5432/dbname (see .env.example)."
        )
    # SQLAlchemy needs the explicit psycopg (v3) driver name.
    if raw.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw[len("postgresql://"):]
    if raw.startswith("postgres://"):
        return "postgresql+psycopg://" + raw[len("postgres://"):]
    return raw


DATABASE_URL = _resolve_url()

engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    pool_size=int(os.environ.get("STARSAGE_PG_POOL", "5")),
    pool_timeout=float(os.environ.get("STARSAGE_PG_POOL_TIMEOUT", "20")),
    connect_args={"connect_timeout": int(os.environ.get("STARSAGE_PG_CONNECT_TIMEOUT", "12"))},
)
Session = sessionmaker(bind=engine, expire_on_commit=False)


def backend_name() -> str:
    return "postgres"


def target() -> str:
    """Human-readable target for logs — never leaks the password."""
    return make_url(DATABASE_URL).render_as_string(hide_password=True)
