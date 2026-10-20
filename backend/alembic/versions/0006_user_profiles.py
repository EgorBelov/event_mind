"""P0 №4: текстовый профиль пользователя (user_profiles)

Свободный текст «о себе» + структурная выжимка LLM (роль, уровень, стек,
интересы, анти-интересы, цели) + эмбеддинг профиля. Итоговый вектор
пользователя по-прежнему в users.embedding (Rocchio: профиль + история).

Revision ID: 0006_user_profiles
Revises: 0005_notifications
Create Date: 2026-10-20
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0006_user_profiles"
down_revision: str | None = "0005_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 384


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("about", sa.Text(), nullable=False, server_default=""),
        sa.Column("role", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="any"),
        sa.Column("stack", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("interests", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("anti_interests", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("goals", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("user_profiles")
