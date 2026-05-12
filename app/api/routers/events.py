from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.api.services.event_service import (
    get_all_events,
    get_event_topic_codes,
    load_events_from_json,
)
from app.api.services.search_service import search_events, get_similar_events

router = APIRouter(prefix="/events", tags=["events"])


def _serialize(event) -> dict:
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "format": event.format,
        "city": event.city,
        "level": event.level,
        "date": event.date,
        "topics": get_event_topic_codes(event),
        "target_audience": getattr(event, "target_audience", None),
        "source_url": event.source_url,
        "summary": getattr(event, "summary", None),
    }


@router.post("/load")
def load_events(db: Session = Depends(get_db)):
    """Load events from data/events.json."""
    count = load_events_from_json(db)
    return {"loaded": count}


@router.get("/")
def list_events(db: Session = Depends(get_db)):
    return [_serialize(e) for e in get_all_events(db)]


@router.get("/search")
def search(
    q: str | None = Query(default=None),
    topics: str | None = Query(default=None),
    format: str | None = Query(default=None),
    city: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    topic_list = [t.strip() for t in topics.split(",")] if topics else None
    return search_events(db, query=q, topics=topic_list, format=format, city=city)


@router.get("/{event_id}/similar")
def similar_events(
    event_id: int,
    limit: int = Query(default=3, ge=1, le=10),
    db: Session = Depends(get_db),
):
    return get_similar_events(db, event_id=event_id, limit=limit)
