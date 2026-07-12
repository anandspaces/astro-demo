"""app_settings: chosen model id per provider

Lets the console pick a specific model name per provider (fetched live from the
provider API); nullable, falling back to the provider default.

Revision ID: d1e2f3a4b5c6
Revises: c1a2b3d4e5f6
Create Date: 2026-07-12 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c1a2b3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('app_settings', sa.Column('claude_model', sa.String(), nullable=True))
    op.add_column('app_settings', sa.Column('gpt_model', sa.String(), nullable=True))
    op.add_column('app_settings', sa.Column('gemini_model', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('app_settings', 'gemini_model')
    op.drop_column('app_settings', 'gpt_model')
    op.drop_column('app_settings', 'claude_model')
