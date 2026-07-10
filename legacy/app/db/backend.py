"""Определение SQL-backend'а из DATABASE_URL.

Используется в embeddings.py / retrieval.py / dedup.py, чтобы выбирать
между JSON-фолбэком (SQLite) и нативным pgvector (PostgreSQL) без
дублирования логики разбора URL.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings

EMBEDDING_DIM = 384  # paraphrase-multilingual-MiniLM-L12-v2 — фиксировано.


@lru_cache(maxsize=1)
def is_postgres() -> bool:
    url = (settings.database_url or "").lower()
    return url.startswith("postgresql") or url.startswith("postgres://")


@lru_cache(maxsize=1)
def has_pgvector() -> bool:
    """PG-backend + установленный pgvector-extension + python-pakage `pgvector`.

    Решение лениво кэшируется: первый вызов сходит в БД (`SELECT extname`),
    последующие — берут результат из lru_cache. На SQLite сразу False.
    """
    if not is_postgres():
        return False
    try:
        import pgvector  # noqa: F401
    except ImportError:
        return False
    try:
        from sqlalchemy import text

        from app.db.session import engine
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            ).first()
            return row is not None
    except Exception:
        return False
