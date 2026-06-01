"""Общие утилиты без зависимостей от БД/HTTP.

Сюда выносится короткий шаринг между модулями, чтобы не плодить
duplicate helpers (раньше `_utcnow_naive` была определена в шести местах
с идентичной реализацией).
"""
from __future__ import annotations

from datetime import UTC, datetime


def utcnow_naive() -> datetime:
    """Текущий UTC без tzinfo — для совместимости с naive-колонками SQLAlchemy.

    PostgreSQL хранит DateTime без зоны как `TIMESTAMP WITHOUT TIME ZONE`.
    SQLite хранит как строку. И там, и там удобнее работать с naive-объектами,
    чтобы избежать неявных конверсий при сравнении.
    """
    return datetime.now(UTC).replace(tzinfo=None)
