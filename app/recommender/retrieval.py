"""Retrieval-слой для RAG: подбор релевантных событий и контекста взаимодействий.

Используется Copilot'ом, чтобы вместо «все события подряд» подавать в LLM
только top-k семантически близких к цели пользователя + срез его истории.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.event_filters import upcoming_only
from app.db.models.event import Event
from app.db.models.interaction import Interaction
from app.db.models.user import User
from app.recommender.scoring import _get_event_topic_codes


def retrieve_events_for_query(
    db: Session,
    user: User,
    query: str,
    k: int = 10,
    candidate_pool: int = 200,
) -> list[dict[str, Any]]:
    """Найти top-k событий, наиболее близких к запросу пользователя.

    Семантика: эмбеддинг(query) ⊕ эмбеддинг(user) (50/50) → cosine vs event.

    Backend:
    - PostgreSQL + pgvector: top-k через `embedding_vec <=> :query` (индекс IVFFlat).
    - SQLite или нет pgvector: in-process сортировка по cosine_similarity.

    Если sentence-transformers недоступен — отдаём fallback по подстроке.
    Возвращает список dict с полями для Copilot-промпта + `_score`.
    """
    try:
        import numpy as np

        from app.recommender.embeddings import (
            cosine_similarity,
            embed_text,
            ensure_event_embeddings,
            get_or_build_user_embedding,
            pgvector_top_k_events,
        )

        q_emb = np.array(embed_text(query), dtype=float)
        try:
            u_emb = np.array(get_or_build_user_embedding(user), dtype=float)
            combined = (q_emb / (np.linalg.norm(q_emb) + 1e-9)) * 0.5 + (
                u_emb / (np.linalg.norm(u_emb) + 1e-9)
            ) * 0.5
        except Exception:
            combined = q_emb

        # Fast path: pgvector — оператор <=> сам отсортирует и ограничит до k.
        # Берём с запасом (k*3): часть pg_ids после фильтра прошедших событий
        # отвалится, нам нужно ≥k оставшихся.
        pg_ids = pgvector_top_k_events(db, combined.tolist(), k=k * 3)
        if pg_ids:
            id_to_event = {
                e.id: e for e in upcoming_only(db.query(Event))
                .filter(Event.id.in_(pg_ids)).all()
            }
            ordered = [id_to_event[i] for i in pg_ids if i in id_to_event][:k]
            return [_serialize_event(e, score=None) for e in ordered]

        # Slow path (SQLite / нет pgvector): подгружаем кандидатов, считаем cosine в Python.
        events = upcoming_only(db.query(Event)).limit(candidate_pool).all()
        if not events:
            return []
        ensure_event_embeddings(db, events)

        scored: list[tuple[float, Event]] = []
        for e in events:
            raw = getattr(e, "embedding", None)
            if not raw:
                continue
            try:
                vec = json.loads(raw)
            except Exception:
                continue
            sim = cosine_similarity(combined.tolist(), vec)
            scored.append((sim, e))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:k]
        return [_serialize_event(e, score=round(score, 3)) for score, e in top]

    except Exception:
        # Fallback: грубое совпадение по подстроке.
        events = upcoming_only(db.query(Event)).limit(candidate_pool).all()
        q_low = query.lower()
        ranked = sorted(
            events,
            key=lambda e: int(q_low in (e.title or "").lower())
            + int(q_low in (e.description or "").lower()),
            reverse=True,
        )
        return [_serialize_event(e, score=None) for e in ranked[:k]]


def build_interaction_context(
    db: Session,
    user: User,
    max_items: int = 8,
) -> dict[str, Any]:
    """Срез истории взаимодействий для подмешивания в Copilot-промпт.

    Возвращает структуру:
        {
            "summary": "лайков 5, сохранений 3, дизлайков 1",
            "liked": [{"title": ..., "topics": [...]}, ...],
            "disliked": [{"title": ..., "topics": [...]}, ...],
            "saved": [...],
        }
    Список ограничен max_items для каждой категории — чтобы не раздувать промпт.
    """
    interactions = (
        db.query(Interaction)
        .filter(Interaction.user_id == user.id)
        .order_by(Interaction.id.desc())
        .all()
    )
    if not interactions:
        return {"summary": "нет истории", "liked": [], "disliked": [], "saved": []}

    liked_n = sum(1 for i in interactions if i.action == "like")
    saved_n = sum(1 for i in interactions if i.action == "save")
    disliked_n = sum(1 for i in interactions if i.action == "dislike")

    event_ids = list({i.event_id for i in interactions})
    events_map = {e.id: e for e in db.query(Event).filter(Event.id.in_(event_ids)).all()}

    def _take(action: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i in interactions:
            if i.action != action:
                continue
            ev = events_map.get(i.event_id)
            if ev is None:
                continue
            out.append({
                "title": ev.title,
                "topics": list(_get_event_topic_codes(ev)),
            })
            if len(out) >= max_items:
                break
        return out

    return {
        "summary": f"лайков {liked_n}, сохранений {saved_n}, дизлайков {disliked_n}",
        "liked": _take("like"),
        "saved": _take("save"),
        "disliked": _take("dislike"),
    }


def _serialize_event(event: Event, score: float | None) -> dict[str, Any]:
    return {
        "id": event.id,
        "title": event.title,
        "description": (event.description or "")[:400],
        "format": event.format,
        "city": event.city,
        "level": event.level,
        "date": event.date,
        "topics": list(_get_event_topic_codes(event)),
        "_score": score,
    }
