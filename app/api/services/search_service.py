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
    """Keyword search: filter by title/description, topics, format, city."""
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
    """Semantic search: rank events by embedding cosine similarity to the query text.

    Falls back to keyword search if embeddings are unavailable.
    """
    try:
        from app.recommender.embeddings import embed_text, cosine_similarity, get_or_build_event_embedding

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


def get_similar_events(db: Session, event_id: int, limit: int = 3) -> list[dict]:
    """Return events sharing the most topics with the given event."""
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
