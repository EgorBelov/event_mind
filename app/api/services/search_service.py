from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models.event import Event
from app.recommender.scoring import _get_event_topic_codes


def _serialize_event(event: Event) -> dict:
    data = {
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
    }
    summary = getattr(event, "summary", None)
    if summary:
        data["summary"] = summary
    return data


def search_events(
    db: Session,
    query: str | None = None,
    topics: list[str] | None = None,
    format: str | None = None,
    city: str | None = None,
) -> list[dict]:
    """Filter events by title/description query, topics, format, and city."""
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


def get_similar_events(db: Session, event_id: int, limit: int = 3) -> list[dict]:
    """Return events that share the most topics with the given event."""
    base = db.query(Event).filter(Event.id == event_id).first()
    if not base:
        return []

    base_topics = _get_event_topic_codes(base)
    if not base_topics:
        return []

    others = db.query(Event).filter(Event.id != event_id).all()
    scored = []
    for e in others:
        overlap = len(_get_event_topic_codes(e).intersection(base_topics))
        if overlap > 0:
            scored.append((overlap, e))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [_serialize_event(e) for _, e in scored[:limit]]
