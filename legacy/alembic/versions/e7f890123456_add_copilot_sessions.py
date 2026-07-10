"""add copilot_sessions

Revision ID: e7f890123456
Revises: d6e7f8901234
Create Date: 2026-05-21 00:02:00.000000

"""
import sqlalchemy as sa

from alembic import op

revision = "e7f890123456"
down_revision = "d6e7f8901234"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copilot_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("messages_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("closed", sa.Integer(), server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("copilot_sessions")
