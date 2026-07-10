"""Метрики ранжирования (single-relevant leave-one-out) + coverage/diversity.

В leave-one-out у каждого пользователя ровно одно «целевое» (скрытое) событие —
поэтому Recall@k ∈ {0,1}, а IDCG=1 (идеальный ранг — первый). Метрики усредняются
по пользователям снаружи.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

from eventmind.domain.recommender.scoring import cosine_similarity


def _rank_of(ranked_ids: Sequence[int], target_id: int) -> int | None:
    """1-индексная позиция target в списке, либо None если его нет."""
    for i, eid in enumerate(ranked_ids):
        if eid == target_id:
            return i + 1
    return None


def recall_at_k(ranked_ids: Sequence[int], target_id: int, k: int) -> float:
    """1.0 если целевое событие попало в top-k, иначе 0.0."""
    rank = _rank_of(ranked_ids[:k], target_id)
    return 1.0 if rank is not None else 0.0


def ndcg_at_k(ranked_ids: Sequence[int], target_id: int, k: int) -> float:
    """nDCG@k для одного релевантного: 1/log2(rank+1) при rank≤k, иначе 0."""
    rank = _rank_of(ranked_ids[:k], target_id)
    if rank is None:
        return 0.0
    return 1.0 / math.log2(rank + 1)


def average_precision(ranked_ids: Sequence[int], target_id: int) -> float:
    """AP для одного релевантного = 1/rank (0, если не найден)."""
    rank = _rank_of(ranked_ids, target_id)
    return 0.0 if rank is None else 1.0 / rank


def catalog_coverage(recommended_ids: set[int], catalog_size: int) -> float:
    """Доля каталога, хоть раз попавшая в выдачу (0..1)."""
    if catalog_size <= 0:
        return 0.0
    return len(recommended_ids) / catalog_size


def intra_list_diversity(
    ranked_ids: Sequence[int], embeddings: dict[int, list[float]]
) -> float:
    """Средняя (1 - cosine) по всем парам выдачи — выше = разнообразнее (0..1)."""
    ids = [eid for eid in ranked_ids if eid in embeddings]
    if len(ids) < 2:
        return 0.0
    total = 0.0
    pairs = 0
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            total += 1.0 - cosine_similarity(embeddings[ids[i]], embeddings[ids[j]])
            pairs += 1
    return total / pairs if pairs else 0.0
