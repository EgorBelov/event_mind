"""Настройки гибридного поиска (P1 №7, №16)."""
from __future__ import annotations

from dataclasses import dataclass

from eventmind.domain.search.fusion import K_DEFAULT


@dataclass(frozen=True, slots=True)
class SearchConfig:
    # false — только строгий поиск по фильтрам (как до P1 №7)
    hybrid: bool = True
    # HyDE: LLM пишет «идеальное событие» под запрос, ищем по его эмбеддингу
    hyde: bool = False
    candidates: int = 30  # глубина каждого ретривера перед слиянием
    rrf_k: int = K_DEFAULT
    # нижняя граница cosine для kNN: без неё семантика всегда что-то «находит»
    min_similarity: float = 0.3
