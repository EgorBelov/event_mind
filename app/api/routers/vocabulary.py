"""Endpoint'ы динамического словаря.

Возвращают актуальный набор тем / городов / форматов / уровней — нужны
мастеру настройки бота и любому фронту, который хочет показать реальные
варианты, включая новые значения, появившиеся из спарсенных событий.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.topics import (
    city_label,
    format_label,
    get_known_cities,
    get_known_formats,
    get_known_levels,
    get_known_topic_codes,
    level_label,
    topic_title,
)
from app.db.dependencies import get_db

router = APIRouter(prefix="/vocabulary", tags=["vocabulary"])


@router.get("/topics")
def list_topics(db: Session = Depends(get_db)) -> list[dict]:
    """Seed-темы + всё, что уже лежит в таблице `topics`."""
    return [{"code": code, "title": topic_title(code)} for code in get_known_topic_codes(db)]


@router.get("/cities")
def list_cities(db: Session = Depends(get_db)) -> list[dict]:
    return [{"code": code, "title": city_label(code)} for code in get_known_cities(db)]


@router.get("/formats")
def list_formats(db: Session = Depends(get_db)) -> list[dict]:
    return [{"code": code, "title": format_label(code)} for code in get_known_formats(db)]


@router.get("/levels")
def list_levels(db: Session = Depends(get_db)) -> list[dict]:
    return [{"code": code, "title": level_label(code)} for code in get_known_levels(db)]


@router.get("")
def list_all(db: Session = Depends(get_db)) -> dict:
    """Полный snapshot словаря в одном запросе."""
    return {
        "topics": list_topics(db),
        "cities": list_cities(db),
        "formats": list_formats(db),
        "levels": list_levels(db),
    }
