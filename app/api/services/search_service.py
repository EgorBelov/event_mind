from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models.event import Event
from app.recommender.scoring import _get_event_topic_codes


def _serialize_event(event: Event) -> dict:
    return {
        "event_id": event.id,
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "format": event.format,
        "city": event.city,
        "level": event.level,
        "date": event.date,
        "topics": list(_get_event_topic_codes(event)),
        "source_url": event.source_url,
        "summary": getattr(event, "summary", None),
        "tech_stack": _parse_json_field(getattr(event, "tech_stack", None)),
        "seniority": getattr(event, "seniority", None),
        "quality_score": getattr(event, "quality_score", None),
        "hype_score": getattr(event, "hype_score", None),
    }


def _parse_json_field(value) -> list:
    if not value:
        return []
    try:
        import json
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def search_events(
    db: Session,
    query: str | None = None,
    topics: list[str] | None = None,
    format: str | None = None,
    city: str | None = None,
) -> list[dict]:
    """Поиск по ключевым словам: фильтры по title/description, темам, формату, городу."""
    q = db.query(Event)

    if query:
        like_pattern = f"%{query.lower()}%"
        q = q.filter(
            or_(
                Event.title.ilike(like_pattern),
                Event.description.ilike(like_pattern),
            )
        )

    if format:
        q = q.filter(Event.format == format)

    if city:
        q = q.filter(Event.city == city)

    events = q.all()

    if topics:
        wanted = set(topics)
        events = [e for e in events if _get_event_topic_codes(e).intersection(wanted)]

    return [_serialize_event(e) for e in events]


def semantic_search_events(db: Session, query: str, limit: int = 5) -> list[dict]:
    """Семантический поиск: ранжирование событий по cosine-сходству embedding'ов.

    При недоступности embedding'ов откатывается к keyword-поиску.
    """
    try:
        from app.recommender.embeddings import (
            cosine_similarity,
            embed_text,
            get_or_build_event_embedding,
        )

        query_emb = embed_text(query)
        events = db.query(Event).all()

        scored: list[tuple[float, Event]] = []
        for event in events:
            try:
                event_emb = get_or_build_event_embedding(event)
                sim = cosine_similarity(query_emb, event_emb)
                scored.append((sim, event))
            except Exception:
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {**_serialize_event(e), "similarity": round(sim, 3)}
            for sim, e in scored[:limit]
        ]

    except Exception:
        return search_events(db, query=query)[:limit]


_GOAL_KEYWORDS = (
    "хочу", "хотел бы", "нужно", "нужен план", "как мне", "посоветуй",
    "план", "roadmap", "карьер", "развив", "вырасти", "стать",
    "перейти", "научиться", "подтянуть", "обучен", "освоить",
    "стажир", "помоги собрать",
)


def _detect_goal_intent(query: str) -> bool:
    """Эвристика: похож ли запрос на «целеполагающий» (для роутинга в Copilot).

    Срабатывает, если запрос длиннее ~30 символов И содержит хотя бы одно
    ключевое слово цели/планирования. Короткие keyword-запросы вроде
    «python митап» сюда не попадают.
    """
    if not query:
        return False
    q = query.lower().strip()
    if len(q) < 30:
        return False
    return any(kw in q for kw in _GOAL_KEYWORDS)


def combined_search(
    db: Session,
    query: str,
    keyword_limit: int = 3,
    semantic_limit: int = 5,
) -> dict:
    """Объединённый поиск: keyword (точные) + semantic (по смыслу) с дедупликацией.

    Возвращает три поля:
      - keyword: до `keyword_limit` событий, найденных по подстроке title/description
      - semantic: до `semantic_limit` событий по cosine-сходству эмбеддингов,
        исключая event_id, уже попавшие в keyword.
      - goal_intent: bool — похож ли запрос на «целеполагающий». Если true,
        бот предложит дополнительно прогнать его через Copilot.
    """
    if not query or not query.strip():
        return {"keyword": [], "semantic": [], "goal_intent": False}

    keyword_hits = search_events(db, query=query)[:keyword_limit]
    keyword_ids = {e["event_id"] for e in keyword_hits}

    # Запросим с запасом, потом отфильтруем дубли.
    semantic_pool = semantic_search_events(db, query=query, limit=semantic_limit + keyword_limit)
    semantic_hits = [e for e in semantic_pool if e["event_id"] not in keyword_ids][:semantic_limit]

    return {
        "keyword": keyword_hits,
        "semantic": semantic_hits,
        "goal_intent": _detect_goal_intent(query),
    }


def get_similar_events(db: Session, event_id: int, limit: int = 3) -> list[dict]:
    """Найти события с максимальным пересечением тем относительно заданного."""
    base = db.query(Event).filter(Event.id == event_id).first()
    if not base:
        return []

    base_topics = _get_event_topic_codes(base)
    if not base_topics:
        return []

    others = db.query(Event).filter(Event.id != event_id).all()
    scored = [
        (len(_get_event_topic_codes(e).intersection(base_topics)), e)
        for e in others
        if _get_event_topic_codes(e).intersection(base_topics)
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [_serialize_event(e) for _, e in scored[:limit]]
