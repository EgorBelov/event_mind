"""add user_memories table (long-term memory agent)

Revision ID: abcd1234ef56
Revises: f8901234abcd
Create Date: 2026-05-21 00:04:00.000000

"""
import sqlalchemy as sa

from alembic import op

revision = "abcd1234ef56"
down_revision = "f8901234abcd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_memories",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("salience", sa.Float(), nullable=False, server_default="5.0"),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("user_memories")
