"""M4: рекомендер (interactions, user_topic_stats, user prefs)

Revision ID: 0004_recommender
Revises: 0003_ingestion
Create Date: 2026-07-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_recommender"
down_revision: str | None = "0003_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("city", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("preferred_format", sa.String(length=16), nullable=True))

    op.create_table(
        "interactions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_interactions_user_id", "interactions", ["user_id"])
    op.create_index("ix_interactions_event_id", "interactions", ["event_id"])

    op.create_table(
        "user_topic_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("alpha", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("beta", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "topic_id", name="uq_user_topic_stat"),
    )
    op.create_index("ix_user_topic_stats_user_id", "user_topic_stats", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_topic_stats")
    op.drop_index("ix_interactions_event_id", table_name="interactions")
    op.drop_index("ix_interactions_user_id", table_name="interactions")
    op.drop_table("interactions")
    op.drop_column("users", "preferred_format")
    op.drop_column("users", "city")
