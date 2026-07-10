"""M0: pgvector extension + служебная таблица schema_marker

Первая консистентная миграция v2. Включает расширение `vector` (pgvector
с день-1, как требует REBUILD_PROMPT) и создаёт лёгкую служебную таблицу,
чтобы миграционная инфраструктура работала end-to-end до появления доменной
схемы. Полная схема агрегатов (users, user_channels, outbox, events, ...)
создаётся одной консистентной миграцией в M1.

Revision ID: 0001_initial_pgvector
Revises:
Create Date: 2026-07-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_pgvector"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector: тип vector + операторы <->, <=>, <#> и HNSW-индексы (нужно с M1).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Служебная таблица: отметка о применённой схеме v2. В M1 к ней добавятся
    # доменные таблицы; сейчас она подтверждает, что миграции идут end-to-end.
    op.create_table(
        "schema_marker",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("component", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute(
        "INSERT INTO schema_marker (component) VALUES ('m0-skeleton')"
    )


def downgrade() -> None:
    op.drop_table("schema_marker")
    op.execute("DROP EXTENSION IF EXISTS vector")
