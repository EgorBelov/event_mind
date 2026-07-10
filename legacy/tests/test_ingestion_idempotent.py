"""Тесты idempotent-обновления существующих событий при re-ingestion."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.services.ingestion_service import _merge_existing_event
from app.db.base import Base
from app.db.models.event import Event


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _make_event(db, **overrides) -> Event:
    base = {
        "title": "PyConf 2026",
        "description": "old",
        "format": "unknown",
        "city": "unknown",
        "level": "any",
        "date": "",
        "start_at": None,
        "source_url": None,
        "event_type": "unknown",
        "seniority": "any",
        "quality_score": None,
        "hype_score": None,
        "target_audience": "",
    }
    base.update(overrides)
    e = Event(**base)
    db.add(e)
    db.commit()
    return e


def test_fills_missing_url(db):
    e = _make_event(db)
    _merge_existing_event(e, {"source_url": "https://x"}, new_date="", new_url="https://x")
    assert e.source_url == "https://x"


def test_does_not_overwrite_existing_url(db):
    e = _make_event(db, source_url="https://old")
    _merge_existing_event(e, {"source_url": "https://new"}, new_date="", new_url="https://new")
    # Существующий URL приоритетнее — не молчаливо подменяем чужими ссылками
    assert e.source_url == "https://old"


def test_fills_missing_date(db):
    e = _make_event(db)
    _merge_existing_event(e, {"format": "online"}, new_date="2026-07-01", new_url=None)
    assert e.date == "2026-07-01"
    assert e.start_at is not None


def test_updates_date_when_changed(db):
    """Анонс серии повторился с уточнённой датой — обновляем."""
    from datetime import datetime
    e = _make_event(db, date="2026-06-01", start_at=datetime(2026, 6, 1))
    _merge_existing_event(e, {"format": "online"}, new_date="2026-06-15", new_url=None)
    assert e.date == "2026-06-15"
    assert e.start_at == datetime(2026, 6, 15)


def test_upgrades_format_from_unknown(db):
    e = _make_event(db, format="unknown")
    _merge_existing_event(e, {"format": "offline"}, new_date="", new_url=None)
    assert e.format == "offline"


def test_does_not_downgrade_known_format(db):
    e = _make_event(db, format="offline")
    _merge_existing_event(e, {"format": "online"}, new_date="", new_url=None)
    # неизвестный (новый) хуже известного (старого) — не трогаем
    assert e.format == "offline"


def test_description_extended_when_significantly_longer(db):
    e = _make_event(db, description="short note")
    long_desc = "This is a much longer and richer description with details. " * 5
    _merge_existing_event(e, {"description": long_desc}, new_date="", new_url=None)
    assert e.description == long_desc.strip()


def test_description_not_replaced_when_similar_length(db):
    e = _make_event(db, description="The original event description text with some details.")
    _merge_existing_event(
        e, {"description": "Slightly different but similar length"},
        new_date="", new_url=None,
    )
    assert e.description.startswith("The original")


def test_fills_missing_quality_score(db):
    e = _make_event(db)
    _merge_existing_event(e, {"quality_score": 8, "hype_score": 7}, new_date="", new_url=None)
    assert e.quality_score == 8
    assert e.hype_score == 7
