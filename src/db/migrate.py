"""Programmatic Alembic wrapper so the app can apply migrations from code
(`store.init_db()`, `main.py migrate`, server startup) without shelling out."""
import os

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from .database import engine

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))  # project root (holds alembic.ini)


def _config():
    return Config(os.path.join(ROOT, "alembic.ini"))


def current_revision():
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def head_revision():
    return ScriptDirectory.from_config(_config()).get_current_head()


def upgrade():
    """Apply all pending migrations. Returns (previous_revision, new_revision)."""
    before = current_revision()
    command.upgrade(_config(), "head")
    return before, current_revision()


def status():
    return {"current": current_revision(), "head": head_revision()}
