"""A3: журнал вызовов инструментов агента (agent_tool_calls)

Одна строка на вызов инструмента: аргументы, статус (ok / invalid / rejected /
pending / confirmed / declined / error), задержка, причина остановки хода.

Revision ID: 0008_agent_tool_calls
Revises: 0007_users_email_nullable
Create Date: 2026-10-27
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_agent_tool_calls"
down_revision: str | None = "0007_users_email_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stop_reason", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_tool_calls_user_id", "agent_tool_calls", ["user_id"])
    op.create_index("ix_agent_tool_calls_session_id", "agent_tool_calls", ["session_id"])
    op.create_index("ix_agent_tool_calls_created_at", "agent_tool_calls", ["created_at"])


def downgrade() -> None:
    op.drop_table("agent_tool_calls")
