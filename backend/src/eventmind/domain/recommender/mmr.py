"""MMR-rerank + series anti-flood (порт из v1 diversity.py и series-логики).

MMR на каждом шаге выбирает кандидата, максимизирующего
    λ·relevance(e) − (1−λ)·max_sim(e, picked).
λ=1.0 — чистый relevance, λ=0.0 — чистая диверсификация.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from eventmind.domain.recommender.scoring import cosine_similarity

DEFAULT_MMR_TOP_N = 30


@dataclass(slots=True)
class RankedItem:
    event_id: int
    score: float
    embedding: list[float] | None = None
    series_slug: str | None = None
    start_at: datetime | None = None


def mmr_rerank(
    items: list[RankedItem], *, lambda_: float = 0.7, top_n: int | None = None
) -> list[RankedItem]:
    """Диверсифицировать голову отсортированного по score списка через MMR.

    Хвост (за top_n) возвращается как есть — он всё равно низкого качества.
    Без эмбеддингов MMR деградирует до исходного порядка.
    """
    if not items:
        return items
    limit = min(DEFAULT_MMR_TOP_N, len(items)) if top_n is None else min(top_n, len(items))
    head, tail = items[:limit], items[limit:]

    scores = [it.score for it in head]
    s_max, s_min = max(scores), min(scores)
    rng = (s_max - s_min) or 1.0
    norm_rel = {it.event_id: (it.score - s_min) / rng for it in head}

    picked: list[RankedItem] = []
    remaining = list(head)
    while remaining:
        best_idx = 0
        best_value = float("-inf")
        for idx, cand in enumerate(remaining):
            rel = norm_rel[cand.event_id]
            if not picked or cand.embedding is None:
                penalty = 0.0
            else:
                sims = [
                    cosine_similarity(cand.embedding, p.embedding)
                    for p in picked
                    if p.embedding is not None
                ]
                penalty = max(sims) if sims else 0.0
            value = lambda_ * rel - (1.0 - lambda_) * penalty
            if value > best_value:
                best_value, best_idx = value, idx
        picked.append(remaining.pop(best_idx))
    return picked + tail


def series_anti_flood(items: list[RankedItem], *, now: datetime) -> list[RankedItem]:
    """Оставить по одному выпуску на серию — ближайший по start_at к `now`.

    События без series_slug не трогаем. Порядок остальных сохраняется.
    """
    by_id = {i.event_id: i for i in items}

    def distance(it: RankedItem) -> float:
        if it.start_at is None:
            return float("inf")
        return abs((it.start_at - now).total_seconds())

    # Для каждой серии выбираем «победителя» — ближайший к now выпуск.
    winners: dict[str, int] = {}
    for it in items:
        if not it.series_slug:
            continue
        cur = winners.get(it.series_slug)
        if cur is None or distance(it) < distance(by_id[cur]):
            winners[it.series_slug] = it.event_id

    # Пересобираем: пропускаем members серии, кроме победителя.
    out: list[RankedItem] = []
    for it in items:
        if it.series_slug and winners.get(it.series_slug) != it.event_id:
            continue
        out.append(it)
    return out
