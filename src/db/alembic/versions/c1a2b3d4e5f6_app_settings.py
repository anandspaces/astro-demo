"""app_settings: console LLM provider + encrypted API keys

A single-row settings table so the web console can switch models and store the
provider API key (encrypted by the app) in the database, surviving refreshes.
Scoping moves to per-account when authentication is added.

Revision ID: c1a2b3d4e5f6
Revises: b44af1795ff0
Create Date: 2026-07-12 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = 'b44af1795ff0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'app_settings',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('claude_key_enc', sa.String(), nullable=True),
        sa.Column('gpt_key_enc', sa.String(), nullable=True),
        sa.Column('gemini_key_enc', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('app_settings')
