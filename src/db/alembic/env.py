"""Alembic environment. Resolves the database URL from DATABASE_URL (via db.database)
and targets the SQLAlchemy models' metadata so autogenerate works."""
import os
import sys
from logging.config import fileConfig

from alembic import context

# Make src/ importable (for `db.*`) and load .env from the project root so
# DATABASE_URL is available.
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PROJECT_ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC)


def _load_dotenv():
    import re
    path = os.path.join(PROJECT_ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, raw = line.partition("=")
            key = key.strip()
            val = re.split(r"\s#", raw, maxsplit=1)[0].strip().strip('"').strip("'")
            if key and val and key not in os.environ:
                os.environ[key] = val


_load_dotenv()

from db.database import engine  # noqa: E402
from db.models import Base      # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online():
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True, render_as_batch=engine.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    context.configure(url=str(engine.url), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
