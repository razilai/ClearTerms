"""preferences.weight -> preferences.enabled

Preferences became a binary checklist. The float weight only ever meant "count
this category" (> 0) or "mute it" (0) — compute_verdict never read the
magnitude — so existing rows convert without loss in either direction.

Revision ID: c1f7a2b93d40
Revises: 40c5f3e43d7d
Create Date: 2026-08-15 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c1f7a2b93d40'
down_revision: str | Sequence[str] | None = '40c5f3e43d7d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Added nullable so the backfill has somewhere to write, then tightened.
    op.add_column('preferences', sa.Column('enabled', sa.Boolean(), nullable=True))
    op.execute('UPDATE preferences SET enabled = (weight > 0)')
    op.alter_column('preferences', 'enabled', nullable=False)
    op.drop_column('preferences', 'weight')


def downgrade() -> None:
    """Downgrade schema."""
    # A muted category is 0.0; everything else returns as full weight, which is
    # what the UI wrote for every checked category anyway.
    op.add_column('preferences', sa.Column('weight', sa.Float(), nullable=True))
    op.execute('UPDATE preferences SET weight = CASE WHEN enabled THEN 1.0 ELSE 0.0 END')
    op.alter_column('preferences', 'weight', nullable=False)
    op.drop_column('preferences', 'enabled')
