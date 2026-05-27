from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.services.ingestion_service import (
    get_ingestion_status,
    load_habr_events,
    load_kudago_events,
    load_luma_events,
    load_meetup_events,
    load_raw_events,
    load_rss_events,
    load_telegram_events,
    normalize_raw_events,
)
from app.db.dependencies import get_db

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


@router.post("/load-kudago")
def load_kudago(limit: int = 20, db: Session = Depends(get_db)):
    """Скачать события из KudaGo (открытый JSON API)."""
    return load_kudago_events(db, limit=limit)


@router.post("/load-luma")
def load_luma(limit_per_calendar: int = 20, db: Session = Depends(get_db)):
    """Скачать события с Lu.ma по ICS-фидам из LUMA_CALENDARS."""
    return load_luma_events(db, limit_per_calendar=limit_per_calendar)


@router.post("/load-meetup")
def load_meetup(limit_per_group: int = 20, db: Session = Depends(get_db)):
    """Скачать события с Meetup (требуется MEETUP_TOKEN + MEETUP_GROUPS)."""
    return load_meetup_events(db, limit_per_group=limit_per_group)


@router.post("/load-telegram")
def load_tg(limit_per_channel: int = 20, db: Session = Depends(get_db)):
    """Скачать события из Telegram-каналов (требуется telethon + TG_*)."""
    return load_telegram_events(db, limit_per_channel=limit_per_channel)


@router.post("/normalize")
def normalize(db: Session = Depends(get_db)):
    """Прогнать pending raw-события через AI-нормализатор и сохранить в events."""
    result = normalize_raw_events(db)
    return result


@router.get("/status")
def ingestion_status(db: Session = Depends(get_db)):
    """Счётчики по статусам raw_events (raw / normalized / non_it / failed)."""
    return get_ingestion_status(db)
