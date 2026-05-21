"""Maximal Marginal Relevance (MMR) diversity re-ranking.

Сценарий: top-N кандидатов из hybrid_score часто одной темы. MMR на каждом
шаге выбирает кандидата, максимизирующего:
    score(e) = λ · relevance(e) − (1 − λ) · max_sim(e, picked)

λ = 1.0 — чистый relevance, λ = 0.0 — чистая диверсификация.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session


def _batch_load_embeddings(db: Session, event_ids: list[int]) -> dict[int, list[float] | None]:
    """Одним SQL получить эмбеддинги для всех нужных событий.

    Раньше делалось N отдельных SELECT'ов через _load_embedding — это
    в худшем случае давало >100 round-trip'ов на одном /recommendations.
    """
    from app.db.models.event import Event
    if not event_ids:
        return {}
    rows = db.query(Event.id, Event.embedding).filter(Event.id.in_(event_ids)).all()
    out: dict[int, list[float] | None] = {eid: None for eid in event_ids}
    for eid, raw in rows:
        if not raw:
            continue
        try:
            out[eid] = json.loads(raw)
        except Exception:
            out[eid] = None
    return out


def _cos(a: list[float], b: list[float]) -> float:
    import numpy as np
    av, bv = np.array(a), np.array(b)
    denom = float(np.linalg.norm(av) * np.linalg.norm(bv) + 1e-9)
    return float(np.dot(av, bv) / denom)


# Дефолтный потолок MMR-окна. На больших каталогах нет смысла гонять
# O(N²) по всей сотне — берём top-N по relevance и диверсифицируем их.
DEFAULT_MMR_TOP_N = 30


def mmr_rerank(
    results: list[dict[str, Any]],
    db: Session,
    lambda_: float = 0.7,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Применить MMR к уже отсортированному по `score` списку результатов.

    На входе ожидается отсортированный по `score` DESC список. Берём первые
    `top_n` кандидатов и диверсифицируем их через MMR (O(top_n²) cos-sim).
    Хвост возвращается «как есть» — он всё равно низкого качества.

    Если у событий нет эмбеддингов в БД, MMR деградирует до исходного порядка.
    """
    if not results:
        return results
    if top_n is None:
        top_n = min(DEFAULT_MMR_TOP_N, len(results))
    else:
        top_n = min(top_n, len(results))

    head = results[:top_n]
    tail = results[top_n:]

    # Нормализуем relevance в [0, 1] чтобы λ-смешение было сопоставимо с cos-sim.
    scores = [float(r.get("score", 0.0)) for r in head]
    s_max = max(scores) or 1.0
    s_min = min(scores)
    rng = (s_max - s_min) or 1.0
    norm_rel = {r["event_id"]: (s - s_min) / rng for r, s in zip(head, scores)}

    embeddings = _batch_load_embeddings(db, [r["event_id"] for r in head])

    picked: list[dict[str, Any]] = []
    remaining = list(head)

    while remaining and len(picked) < top_n:
        best_idx = 0
        best_value = float("-inf")
        for idx, r in enumerate(remaining):
            eid = r["event_id"]
            rel = norm_rel[eid]
            emb = embeddings.get(eid)
            if not picked or emb is None:
                diversity_penalty = 0.0
            else:
                sims = []
                for p in picked:
                    p_emb = embeddings.get(p["event_id"])
                    if p_emb is None:
                        continue
                    sims.append(_cos(emb, p_emb))
                diversity_penalty = max(sims) if sims else 0.0
            value = lambda_ * rel - (1.0 - lambda_) * diversity_penalty
            if value > best_value:
                best_value = value
                best_idx = idx
        picked.append(remaining.pop(best_idx))

    return picked + tail
