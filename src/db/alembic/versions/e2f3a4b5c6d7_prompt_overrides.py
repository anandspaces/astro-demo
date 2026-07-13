"""prompt_overrides: editable pipeline prompts

Stores console-edited overrides for the pipeline prompts (system / planner /
critic / preamble). A present row overrides the hardcoded default in
pipeline/prompts.py; absent falls back to the default. Lets the operator iterate
on prompt/response quality without a redeploy.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-07-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'prompt_overrides',
        sa.Column('name', sa.String(), primary_key=True),
        sa.Column('content', sa.String(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('prompt_overrides')
