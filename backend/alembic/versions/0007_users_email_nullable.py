"""B1: аккаунты, созданные в Telegram-боте, — без email (users.email NULL)

Уникальность email сохраняется для заданных значений (NULL в Postgres не
конфликтуют между собой).

Revision ID: 0007_users_email_nullable
Revises: 0006_user_profiles
Create Date: 2026-10-20
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_users_email_nullable"
down_revision: str | None = "0006_user_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "email", existing_type=sa.String(length=320), nullable=True)


def downgrade() -> None:
    # Telegram-only аккаунты без email не переживут NOT NULL — удаляем их явно.
    op.execute("DELETE FROM users WHERE email IS NULL")
    op.alter_column("users", "email", existing_type=sa.String(length=320), nullable=False)
