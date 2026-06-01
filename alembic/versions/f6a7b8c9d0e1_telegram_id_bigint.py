"""users.telegram_id INTEGER → BIGINT

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-01 14:00:00.000000

Telegram-каналы/группы имеют ID за пределами 2³¹ (часто `-100…`). Под
Postgres `Integer` (int4) переполнялся бы — Supabase возвращал бы 5xx
на регистрации каналов. На SQLite `Integer` и `BigInteger` маппятся
в одну и ту же `INTEGER`, миграция фактически no-op (но идемпотентна).
"""
import sqlalchemy as sa

from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # SQLite не умеет ALTER COLUMN TYPE напрямую и в нашей семантике
    # это ничего не меняет — пропускаем.
    if bind.dialect.name == "sqlite":
        return
    op.alter_column(
        "users", "telegram_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    op.alter_column(
        "users", "telegram_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
