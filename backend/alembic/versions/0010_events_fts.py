"""P1 №7: GIN-индекс полнотекстового поиска по событиям (гибридный поиск)

Выражение должно совпадать с `infrastructure/db/search.py::fts_document`:
to_tsvector('russian', coalesce(title, '') || ' ' || coalesce(description, '')).
Конфигурация russian: кириллица — russian_stem, латиница — english_stem.

Revision ID: 0010_events_fts
Revises: 0009_event_provenance
Create Date: 2026-10-27
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_events_fts"
down_revision: str | None = "0009_event_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_events_fts ON events USING gin "
        "(to_tsvector('russian', coalesce(title, '') || ' ' || coalesce(description, '')))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_events_fts")
