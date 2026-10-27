"""P1 №8: семантические дубли между источниками (raw_events.duplicate_of)

Сырьё, распознанное как то же событие из другого источника, получает статус
`duplicate` и ссылку на существующее событие. Статус — строка, CHECK нет:
схема статусов не меняется.

Revision ID: 0011_raw_events_duplicate_of
Revises: 0010_events_fts
Create Date: 2026-10-27
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_raw_events_duplicate_of"
down_revision: str | None = "0010_events_fts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("raw_events", sa.Column("duplicate_of", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_raw_events_duplicate_of",
        "raw_events",
        "events",
        ["duplicate_of"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_raw_events_duplicate_of", "raw_events", type_="foreignkey")
    op.drop_column("raw_events", "duplicate_of")
