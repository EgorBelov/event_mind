from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.api.services.event_service import (
    get_all_events,
    load_events_from_json,
    load_raw_events_with_ai,
)

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/load")
def load_events(db: Session = Depends(get_db)):
    count = load_events_from_json(db)
    return {"loaded": count}


@router.get("/")
def list_events(db: Session = Depends(get_db)):
    events = get_all_events(db)

    return [
        {
            "id": event.id,
            "title": event.title,
            "description": event.description,
            "format": event.format,
            "city": event.city,
            "level": event.level,
            "date": event.date,
            "topics": event.topics.split(",") if event.topics else [],
        }
        for event in events
    ]

@router.post("/load-ai")
def load_events_ai(db: Session = Depends(get_db)):
    count = load_raw_events_with_ai(db)
    return {"loaded": count}