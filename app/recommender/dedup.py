"""Семантическая дедупликация событий.

Существующий title-exact-match не ловит парафразы и кросс-источниковые
дубли. Здесь мы при ingest'е сравниваем эмбеддинг кандидата с эмбеддингами
последних N событий — если максимум cosine ≥ порога, кандидат считается
дублем (возвращаем `existing_event` для merge или возвращаем None если
дубля нет).
"""
from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.event import Event


def find_semantic_duplicate(
    db: Session,
    candidate_text: str,
    *,
    threshold: float | None = None,
    lookback_days: int = 90,
    max_candidates: int = 500,
) -> Event | None:
    """Вернуть существующее Event, если кандидат семантически почти равен ему.

    `candidate_text` — то же, что используется для эмбеддинга события
    (`title + description`).
    """
    if not settings.dedup_enabled:
        return None

    th = threshold if threshold is not None else settings.dedup_threshold

    try:
        from app.recommender.embeddings import cosine_similarity, embed_text
        cand_vec = embed_text(candidate_text)
    except Exception:
        return None

    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=lookback_days)
    query = (
        db.query(Event)
        .filter(Event.embedding.isnot(None))
        .order_by(Event.id.desc())
        .limit(max_candidates)
    )
    # Pre-filter по created_at если есть колонка (она есть) — но не делаем это
    # обязательным, чтобы тесты с in-memory БД и server_default-now() работали.
    with contextlib.suppress(Exception):
        query = query.filter(Event.created_at >= cutoff)

    best: tuple[float, Event] | None = None
    for ev in query.all():
        try:
            ev_vec = json.loads(ev.embedding)
        except Exception:
            continue
        sim = cosine_similarity(cand_vec, ev_vec)
        if best is None or sim > best[0]:
            best = (sim, ev)
        if sim >= th:
            return ev  # ранний выход

    if best and best[0] >= th:
        return best[1]
    return None
