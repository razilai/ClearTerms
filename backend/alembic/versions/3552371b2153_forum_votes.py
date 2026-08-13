"""forum votes

Revision ID: 3552371b2153
Revises: 2e5220fede24
Create Date: 2026-08-13 12:07:41.183144

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3552371b2153'
down_revision: str | Sequence[str] | None = '2e5220fede24'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing likes become +1 votes. Rename rather than drop/recreate so the
    # rows survive.
    op.rename_table("likes", "post_votes")
    op.alter_column("post_votes", "post_id", new_column_name="target_id")
    op.add_column(
        "post_votes",
        sa.Column("value", sa.SmallInteger(), nullable=False, server_default="1"),
    )
    # The default existed only to backfill the pre-existing rows; the model does
    # not declare one, so drop it or autogenerate will keep flagging a diff.
    op.alter_column("post_votes", "value", server_default=None)
    op.create_check_constraint("ck_post_votes_value", "post_votes", "value IN (-1, 1)")

    # Postgres keeps the old names when a table is renamed, and alembic compares
    # index names — without these renames every future autogenerate would try to
    # drop and recreate them.
    op.execute("ALTER INDEX ix_likes_post_id RENAME TO ix_post_votes_target_id")
    op.execute("ALTER INDEX ix_likes_user_id RENAME TO ix_post_votes_user_id")
    op.execute(
        "ALTER TABLE post_votes RENAME CONSTRAINT likes_user_id_post_id_key "
        "TO post_votes_user_id_target_id_key"
    )

    op.create_table(
        "comment_votes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(["target_id"], ["comments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "target_id"),
        sa.CheckConstraint("value IN (-1, 1)", name="ck_comment_votes_value"),
    )
    op.create_index(
        op.f("ix_comment_votes_target_id"), "comment_votes", ["target_id"], unique=False
    )
    op.create_index(
        op.f("ix_comment_votes_user_id"), "comment_votes", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_comment_votes_user_id"), table_name="comment_votes")
    op.drop_index(op.f("ix_comment_votes_target_id"), table_name="comment_votes")
    op.drop_table("comment_votes")

    # Dislikes have no representation in the old schema — drop them.
    op.execute("DELETE FROM post_votes WHERE value = -1")
    op.execute(
        "ALTER TABLE post_votes RENAME CONSTRAINT post_votes_user_id_target_id_key "
        "TO likes_user_id_post_id_key"
    )
    op.execute("ALTER INDEX ix_post_votes_user_id RENAME TO ix_likes_user_id")
    op.execute("ALTER INDEX ix_post_votes_target_id RENAME TO ix_likes_post_id")
    op.drop_constraint("ck_post_votes_value", "post_votes", type_="check")
    op.drop_column("post_votes", "value")
    op.alter_column("post_votes", "target_id", new_column_name="post_id")
    op.rename_table("post_votes", "likes")
    