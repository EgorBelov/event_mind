"""add user_topic_stats for bayesian online learning

Revision ID: c5d6e7f89012
Revises: b3c4d5e6f7a8
Create Date: 2026-05-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c5d6e7f89012"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_topic_stats",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False, index=True),
        sa.Column("alpha", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("beta", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "topic_id", name="uq_user_topic_stat"),
    )


def downgrade() -> None:
    op.drop_table("user_topic_stats")
