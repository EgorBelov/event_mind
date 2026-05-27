"""Add pgvector extension + vector columns (PostgreSQL only).

Миграция no-op для SQLite: проверяет bind.dialect.name и тихо выходит,
если diolect != postgresql. На PostgreSQL:
  - создаёт расширение pgvector (CREATE EXTENSION IF NOT EXISTS vector),
  - добавляет колонки events.embedding_vec и users.embedding_vec типа vector(384),
  - создаёт IVFFlat-индекс по events.embedding_vec для top-k поиска через <->.

Существующие JSON-Text-колонки `embedding` остаются для обратной совместимости
и dev-окружения на SQLite. Перенос данных JSON → vector выполняется бэкфилл-
скриптом scripts/backfill_pgvector.py.

Revision ID: 9a1b2c3d4e5f
Revises: abcd1234ef56
Create Date: 2026-05-26 12:50:00.000000
"""
from alembic import op

revision = "9a1b2c3d4e5f"
down_revision = "abcd1234ef56"
branch_labels = None
depends_on = None


EMBEDDING_DIM = 384


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    # 1. pgvector-расширение (требует прав на CREATE EXTENSION).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Колонки vector(384) — рядом с существующими Text(JSON) для миграции
    #    без даунтайма. Старый код продолжает писать JSON; новый — пишет в обе.
    op.execute(
        f"ALTER TABLE events ADD COLUMN IF NOT EXISTS embedding_vec vector({EMBEDDING_DIM})"
    )
    op.execute(
        f"ALTER TABLE users  ADD COLUMN IF NOT EXISTS embedding_vec vector({EMBEDDING_DIM})"
    )

    # 3. IVFFlat-индекс по событиям — основной потребитель top-k.
    #    lists=100 — нормальный дефолт для 10k–100k записей; для миллионов
    #    рекомендуется hnsw, но это требует pgvector 0.5+.
    op.execute(
        "CREATE INDEX IF NOT EXISTS events_embedding_vec_idx "
        "ON events USING ivfflat (embedding_vec vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS events_embedding_vec_idx")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS embedding_vec")
    op.execute("ALTER TABLE users  DROP COLUMN IF EXISTS embedding_vec")
    # Расширение оставляем — другие БД-объекты могут от него зависеть.
