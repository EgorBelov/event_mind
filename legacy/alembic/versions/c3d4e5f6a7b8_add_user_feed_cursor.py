"""add users.feed_cursor

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-01 12:00:00.000000

Перенос состояния ленты бота (`user_recommendation_index` — module-dict
в `app/bot/handlers/recommendations.py`) в БД. Теряло позицию при рестарте
процесса и ломалось при >1 воркере. Аддитивная колонка, server_default=0 —
безопасно и на SQLite, и на Supabase.
"""
import sqlalchemy as sa

from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("feed_cursor", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "feed_cursor")
