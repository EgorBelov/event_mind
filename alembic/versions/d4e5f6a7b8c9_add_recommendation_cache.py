"""add recommendation_cache

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-01 12:30:00.000000

TTL-кэш рекомендаций per-user. Раньше /recommendations пересчитывался на
каждый GET (≈10 с на холодном кэше эмбеддингов под Supabase). Здесь
сохраняем результат с expires_at; запись инвалидируется на feedback / edit
профиля / analyze-bio.
"""
import sqlalchemy as sa

from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recommendation_cache",
        sa.Column("telegram_id", sa.BigInteger(), primary_key=True),
        sa.Column("items_json", sa.Text(), nullable=False),
        sa.Column("limit_used", sa.Integer(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_recommendation_cache_expires_at",
        "recommendation_cache",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_recommendation_cache_expires_at", table_name="recommendation_cache")
    op.drop_table("recommendation_cache")
