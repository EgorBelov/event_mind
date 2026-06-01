"""add events.series_slug

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-01 13:00:00.000000

Идентификатор серии событий: одинаковый slug у разных «выпусков» одной
серии (Python MeetUp #14 / #15 / #16). Считается при ingestion из title,
очищенного от номеров серий и дат. Используется для:
  • анти-флуда в /recommendations (не более одного выпуска серии в выдаче),
  • точного «похожие» при наличии series_slug.

Аддитивно — старые события получают NULL, ingestion дозаполнит для новых;
backfill для старых — отдельный скрипт (см. IMPROVEMENTS).
"""
import sqlalchemy as sa

from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("series_slug", sa.String(length=120), nullable=True))
    op.create_index("ix_events_series_slug", "events", ["series_slug"])


def downgrade() -> None:
    op.drop_index("ix_events_series_slug", table_name="events")
    op.drop_column("events", "series_slug")
