"""session_messages: insight_axis + closing_type_used

Rotation state moves onto the message row. store.get_session_state derives
last_mechanism / last_insight_axis / last_closing_type / last_domain from the most
recent assistant turns instead of the mirrored user_sessions columns, so what the
Planner rotates away from is what was actually written.

Both columns are nullable and additive — pre-existing rows read back as NULL and
fall through to the user_sessions mirror.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-07-19 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('session_messages', sa.Column('insight_axis', sa.String(), nullable=True))
    op.add_column('session_messages', sa.Column('closing_type_used', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('session_messages', 'closing_type_used')
    op.drop_column('session_messages', 'insight_axis')
