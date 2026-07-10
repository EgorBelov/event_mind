"""Параметры рекомендера (лимиты кандидатов/выдачи, TTL кэша)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecommenderConfig:
    candidate_limit: int = 100   # сколько кандидатов достаёт первая стадия
    result_limit: int = 20       # размер выдачи после rerank
    cache_ttl_seconds: int = 900  # 15 мин
