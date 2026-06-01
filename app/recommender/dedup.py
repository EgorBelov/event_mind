"""Семантическая дедупликация событий.

Существующий title-exact-match не ловит парафразы и кросс-источниковые
дубли. Здесь мы при ingest'е сравниваем эмбеддинг кандидата с эмбеддингами
последних N событий — если максимум cosine ≥ порога, кандидат считается
дублем (возвращаем `existing_event` для merge или возвращаем None если
дубля нет).

Backend:
- PostgreSQL + pgvector: один `<=>`-запрос с LIMIT 1 — O(log n) на IVFFlat.
- SQLite / нет pgvector: in-process скан последних `max_candidates` событий.
"""
from __future__ import annotations

import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.backend import has_pgvector, is_postgres
from app.db.models.event import Event

logger = logging.getLogger(__name__)


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

    # Fast path: pgvector. Один SQL вместо N json.loads + cosine в Python.
    # Возвращает (Event | None, ok): ok=False означает «запрос упал, не верю
    # результату — лучше прогнать честный in-memory путь как fallback».
    if has_pgvector() and is_postgres():
        hit, ok = _pgvector_nearest_duplicate(
            db, cand_vec, threshold=th, lookback_days=lookback_days,
        )
        if ok:
            return hit

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


def _pgvector_nearest_duplicate(
    db: Session,
    cand_vec: list[float],
    *,
    threshold: float,
    lookback_days: int,
) -> tuple[Event | None, bool]:
    """Один <=>-запрос: ближайшее событие по cosine, отфильтрованное порогом.

    Возвращает (event_or_none, ok):
    - (Event, True) — нашли дубль;
    - (None, True) — точно дубля нет в окне;
    - (None, False) — запрос упал, вызывающая сторона должна fallback'нуться.

    pgvector-оператор `<=>` возвращает cosine-distance ∈ [0..2]. Эквивалент
    cosine_similarity = 1 - distance. Порог по similarity `th` → ограничение
    на distance `1 - th`. Сужаем по created_at, чтобы не сканировать всю
    таблицу при большом каталоге.
    """
    try:
        from sqlalchemy import text
        vec_str = "[" + ",".join(repr(float(x)) for x in cand_vec) + "]"
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=lookback_days)
        # max distance, при котором cosine-sim ≥ threshold
        max_dist = float(1.0 - threshold)
        sql = text(
            "SELECT id FROM events "
            "WHERE embedding_vec IS NOT NULL "
            "  AND (created_at IS NULL OR created_at >= :cutoff) "
            "  AND embedding_vec <=> CAST(:q AS vector) <= :max_dist "
            "ORDER BY embedding_vec <=> CAST(:q AS vector) "
            "LIMIT 1"
        )
        row = db.execute(
            sql, {"q": vec_str, "cutoff": cutoff, "max_dist": max_dist}
        ).first()
        if not row:
            return None, True
        return db.query(Event).filter(Event.id == row[0]).first(), True
    except Exception as e:
        logger.warning("pgvector dedup query failed, falling back to in-memory: %s", e)
        return None, False
