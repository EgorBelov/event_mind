from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.services.event_service import (
    get_all_events,
    get_event_topic_codes,
    load_events_from_json,
)
from app.api.services.search_service import (
    get_similar_events,
    search_events,
    semantic_search_events,
)
from app.db.dependencies import get_db
from app.db.models.event import Event

router = APIRouter(prefix="/events", tags=["events"])


def _serialize(event) -> dict:
    import json

    def _parse_json(val) -> list:
        if not val:
            return []
        try:
            r = json.loads(val)
            return r if isinstance(r, list) else []
        except Exception:
            return []

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
        "tech_stack": _parse_json(getattr(event, "tech_stack", None)),
        "seniority": getattr(event, "seniority", None),
        "quality_score": getattr(event, "quality_score", None),
        "hype_score": getattr(event, "hype_score", None),
    }


@router.post("/load")
def load_events(db: Session = Depends(get_db)):
    """Загрузить события из data/events.json."""
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
    """Поиск по ключевым словам: фильтры по title/description, темам, формату, городу."""
    topic_list = [t.strip() for t in topics.split(",")] if topics else None
    return search_events(db, query=q, topics=topic_list, format=format, city=city)


@router.get("/semantic-search")
def semantic_search(
    q: str = Query(..., description="Запрос на естественном языке"),
    limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """Семантический поиск: ранжирование событий по embedding-сходству с запросом."""
    return semantic_search_events(db, query=q, limit=limit)


@router.get("/{event_id}")
def get_event_by_id(event_id: int, db: Session = Depends(get_db)):
    """Получить одну карточку события — нужно для deep-link'а в боте."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return _serialize(event)


@router.get("/{event_id}/similar")
def similar_events(
    event_id: int,
    limit: int = Query(default=3, ge=1, le=10),
    db: Session = Depends(get_db),
):
    return get_similar_events(db, event_id=event_id, limit=limit)
