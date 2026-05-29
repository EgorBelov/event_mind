"""add events.start_at + raw_events.retry_count

Revision ID: b2c3d4e5f6a7
Revises: 9a1b2c3d4e5f
Create Date: 2026-05-29 22:30:00.000000

Аддитивно (без смены типа существующих колонок) — безопасно и на SQLite, и на
PostgreSQL/Supabase:
  - events.start_at  : распарсенная дата начала (DateTime) для freshness/сортировки;
                       строковая events.date остаётся для отображения в UI.
  - raw_events.retry_count : число неудачных попыток нормализации (retry-failed
                       пропускает события, превысившие лимит попыток).
"""
import sqlalchemy as sa

from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "9a1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("start_at", sa.DateTime(), nullable=True))
    op.add_column(
        "raw_events",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("raw_events", "retry_count")
    op.drop_column("events", "start_at")
