from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.api.services.ingestion_service import (
    load_raw_events,
    load_habr_events,
    load_rss_events,
    normalize_raw_events,
    get_ingestion_status,
)

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/load-raw")
def load_raw(db: Session = Depends(get_db)):
    """Загрузить сырые события из data/events_raw.json в таблицу raw_events."""
    result = load_raw_events(db)
    return result


@router.post("/load-habr")
def load_habr(limit: int = 20, db: Session = Depends(get_db)):
    """Скачать события с Habr, нормализовать через AI-агента, добавить в events."""
    return load_habr_events(db, limit=limit)


@router.post("/load-rss")
def load_rss(limit_per_feed: int = 20, db: Session = Depends(get_db)):
    """Скачать события из всех настроенных RSS-лент (settings.RSS_FEEDS) и нормализовать."""
    return load_rss_events(db, limit_per_feed=limit_per_feed)


@router.post("/normalize")
def normalize(db: Session = Depends(get_db)):
    """Прогнать pending raw-события через AI-нормализатор и сохранить в events."""
    result = normalize_raw_events(db)
    return result


@router.get("/status")
def ingestion_status(db: Session = Depends(get_db)):
    """Счётчики по статусам raw_events (raw / normalized / non_it / failed)."""
    return get_ingestion_status(db)
