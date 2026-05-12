from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.api.services.ingestion_service import (
    load_raw_events,
    load_habr_events,
    normalize_raw_events,
    get_ingestion_status,
)

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/load-raw")
def load_raw(db: Session = Depends(get_db)):
    """Load raw events from data/events_raw.json into the raw_events table."""
    result = load_raw_events(db)
    return result


@router.post("/load-habr")
def load_habr(limit: int = 20, db: Session = Depends(get_db)):
    """Fetch events from Habr, normalize via AI agent, insert into events table."""
    return load_habr_events(db, limit=limit)


@router.post("/normalize")
def normalize(db: Session = Depends(get_db)):
    """Normalize raw events into Event rows using AI agent."""
    result = normalize_raw_events(db)
    return result


@router.get("/status")
def ingestion_status(db: Session = Depends(get_db)):
    """Show raw/normalized/failed counts."""
    return get_ingestion_status(db)
