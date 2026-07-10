"""Декларативная база SQLAlchemy 2.0 для ORM-моделей v2.

Модели-адаптеры (таблицы) объявляются в `infrastructure` и наследуют этот
`Base`. Доменные сущности (`domain/`) остаются чистыми — ORM их не касается;
маппинг между ними и таблицами делают репозитории. Начиная с M1 сюда
подключаются `users`, `user_channels`, `outbox` и др.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Общая метадата для всех таблиц v2 (используется Alembic'ом)."""
