"""SQLAlchemy schema (Part 7). Single source of truth for the database structure;
Alembic autogenerates migrations from this metadata.

JSON columns use PostgreSQL jsonb. Timestamps are timezone-aware.
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = JSONB
TS = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class AppSettings(Base):
    """LLM preferences for the console: the selected provider + provider API keys.
    A single row (id='global') for now; scoping moves to per-account when auth
    lands. Keys are stored Fernet-encrypted (see keystore.encrypt_secret) — never
    plaintext."""
    __tablename__ = "app_settings"
    id: Mapped[str] = mapped_column(String, primary_key=True)     # singleton: 'global'
    provider: Mapped[str | None] = mapped_column(String)          # claude | gpt | gemini | mock
    claude_key_enc: Mapped[str | None] = mapped_column(String)
    gpt_key_enc: Mapped[str | None] = mapped_column(String)
    gemini_key_enc: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime | None] = mapped_column(TS)


class User(Base):
    __tablename__ = "users"
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    dob: Mapped[str | None] = mapped_column(String)
    tob: Mapped[str | None] = mapped_column(String)
    pob: Mapped[str | None] = mapped_column(String)
    timezone: Mapped[str | None] = mapped_column(String)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime | None] = mapped_column(TS)


class UserChart(Base):
    __tablename__ = "user_charts"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    chart_json: Mapped[dict] = mapped_column(JSONType)
    calculated_at: Mapped[datetime | None] = mapped_column(TS)


class UserReadingLedger(Base):
    __tablename__ = "user_reading_ledger"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    domain: Mapped[str] = mapped_column(String, primary_key=True)
    ledger_json: Mapped[dict] = mapped_column(JSONType)
    last_updated: Mapped[datetime | None] = mapped_column(TS)


class UserSession(Base):
    __tablename__ = "user_sessions"
    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String)
    last_mechanism: Mapped[str | None] = mapped_column(String)
    last_domain: Mapped[str | None] = mapped_column(String)
    last_insight_axis: Mapped[str | None] = mapped_column(String)
    interaction_count: Mapped[int] = mapped_column(Integer, default=0)
    last_active: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime | None] = mapped_column(TS)


class SessionMessage(Base):
    __tablename__ = "session_messages"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String)
    user_id: Mapped[str | None] = mapped_column(String)
    role: Mapped[str | None] = mapped_column(String)
    content: Mapped[str | None] = mapped_column(String)
    domain: Mapped[str | None] = mapped_column(String)
    mechanism_used: Mapped[str | None] = mapped_column(String)
    query_type: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime | None] = mapped_column(TS)

    __table_args__ = (Index("idx_session_messages", "session_id", "created_at"),)
