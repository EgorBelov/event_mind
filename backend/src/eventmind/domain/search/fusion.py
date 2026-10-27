"""Reciprocal Rank Fusion (Cormack et al., 2009) — слияние ранжированных списков.

score(d) = Σ_i w_i / (k + rank_i(d)),  rank с 1.

RRF не требует сопоставимых шкал (BM25/ts_rank и cosine несравнимы напрямую),
устойчив к выбросам одного ретривера и почти не требует настройки (k=60 —
значение из статьи). Документ, найденный несколькими ретриверами, поднимается.
"""
from __future__ import annotations

from collections.abc import Hashable, Sequence
from typing import TypeVar

K_DEFAULT = 60

T = TypeVar("T", bound=Hashable)


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[T]],
    *,
    k: int = K_DEFAULT,
    weights: Sequence[float] | None = None,
) -> list[tuple[T, float]]:
    """[(id, score)] по убыванию score; при равенстве — по лучшему рангу, затем
    по порядку первого появления (детерминированно)."""
    if weights is not None and len(weights) != len(rankings):
        raise ValueError("weights и rankings разной длины")
    scores: dict[T, float] = {}
    best_rank: dict[T, int] = {}
    first_seen: dict[T, int] = {}
    order = 0
    for i, ranking in enumerate(rankings):
        w = 1.0 if weights is None else weights[i]
        seen: set[T] = set()
        for rank, item in enumerate(ranking, start=1):
            if item in seen:  # дубль внутри одного списка не усиливает документ
                continue
            seen.add(item)
            scores[item] = scores.get(item, 0.0) + w / (k + rank)
            best_rank[item] = min(best_rank.get(item, rank), rank)
            if item not in first_seen:
                first_seen[item] = order
                order += 1
    return sorted(
        scores.items(), key=lambda kv: (-kv[1], best_rank[kv[0]], first_seen[kv[0]])
    )
