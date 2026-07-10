"""Тесты Postgres/pgvector-путей.

Две группы:
1. Детерминированные unit-тесты бэкенд-детекции и SQLite-fallback — гоняются
   везде (в т.ч. в CI на SQLite).
2. Gated интеграционный смоук на РЕАЛЬНОМ Postgres — выполняется только если
   DATABASE_URL указывает на postgres (локально/Supabase); в CII на SQLite
   автоматически skip.
"""
import pytest

from app.core.config import settings
from app.db import backend


@pytest.fixture
def clear_backend_cache():
    """is_postgres/has_pgvector кэшируются через lru_cache — чистим до и после,
    чтобы monkeypatch DATABASE_URL не протёк в другие тесты."""
    backend.is_postgres.cache_clear()
    backend.has_pgvector.cache_clear()
    yield
    backend.is_postgres.cache_clear()
    backend.has_pgvector.cache_clear()


@pytest.mark.parametrize(
    "url,expected",
    [
        ("postgresql+psycopg2://u:p@h:5432/db", True),
        ("postgres://u:p@h/db", True),
        ("sqlite:///./eventmind.db", False),
        ("", False),
    ],
)
def test_is_postgres_detection(monkeypatch, clear_backend_cache, url, expected):
    monkeypatch.setattr(settings, "database_url", url)
    backend.is_postgres.cache_clear()
    assert backend.is_postgres() is expected


def test_has_pgvector_false_on_sqlite(monkeypatch, clear_backend_cache):
    monkeypatch.setattr(settings, "database_url", "sqlite:///./x.db")
    backend.is_postgres.cache_clear()
    backend.has_pgvector.cache_clear()
    assert backend.has_pgvector() is False


def test_pgvector_top_k_empty_without_pgvector(monkeypatch):
    """Без pgvector функция должна вернуть [] до обращения к БД (db=None безопасен)."""
    from app.recommender import embeddings

    monkeypatch.setattr(embeddings, "has_pgvector", lambda: False)
    monkeypatch.setattr(embeddings, "is_postgres", lambda: False)

    assert embeddings.pgvector_top_k_events(None, [0.1] * 384, k=5) == []


# ── Gated интеграция: реальный Postgres ──────────────────────────────────


@pytest.mark.skipif(
    not backend.is_postgres(),
    reason="needs a Postgres DATABASE_URL (skipped on SQLite/CI)",
)
def test_pgvector_query_executes_on_real_pg():
    """Read-only смоук: <=>-запрос реально исполняется и возвращает список id."""
    from app.db.session import SessionLocal
    from app.recommender.embeddings import pgvector_top_k_events

    assert backend.has_pgvector() is True
    db = SessionLocal()
    try:
        ids = pgvector_top_k_events(db, [0.0] * 384, k=3)
        assert isinstance(ids, list)
        assert all(isinstance(i, int) for i in ids)
    finally:
        db.close()
