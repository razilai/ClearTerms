"""message attachments

Revision ID: 7e3d4ad819d2
Revises: 23b80876278e
Create Date: 2026-08-18 18:22:12.822308

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7e3d4ad819d2'
down_revision: str | Sequence[str] | None = '23b80876278e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('attachments', sa.Column('message_id', sa.Integer(), nullable=True))
    op.create_index(
        'ix_attachments_message_id', 'attachments', ['message_id'], unique=False
    )
    # Named explicitly: autogenerate emitted None, which leaves downgrade with
    # no constraint to drop.
    op.create_foreign_key(
        'attachments_message_id_fkey',
        'attachments',
        'messages',
        ['message_id'],
        ['id'],
        ondelete='CASCADE',
    )
    # Hand-written: alembic does not autogenerate CheckConstraint changes. The
    # old pairwise form only forbade post+comment together, so it would happily
    # allow a row owned by both a message and a post.
    op.drop_constraint('ck_attachments_single_owner', 'attachments', type_='check')
    op.create_check_constraint(
        'ck_attachments_single_owner',
        'attachments',
        'num_nonnulls(post_id, comment_id, message_id) <= 1',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_attachments_single_owner', 'attachments', type_='check')
    # Any attachment owned by a message becomes unlinked rather than violating
    # the restored two-column constraint; the orphan sweep will collect it.
    op.execute(
        'UPDATE attachments SET message_id = NULL WHERE message_id IS NOT NULL'
    )
    op.create_check_constraint(
        'ck_attachments_single_owner',
        'attachments',
        'NOT (post_id IS NOT NULL AND comment_id IS NOT NULL)',
    )
    op.drop_constraint('attachments_message_id_fkey', 'attachments', type_='foreignkey')
    op.drop_index('ix_attachments_message_id', table_name='attachments')
    op.drop_column('attachments', 'message_id')
