"""Тесты TTL-кэша рекомендаций (recommendation_cache)."""
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.services.recommendation_service import (
    _read_recommendation_cache,
    _write_recommendation_cache,
    invalidate_recommendation_cache,
)
from app.db.base import Base
from app.db.models import RecommendationCache, User


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    # Под FK не нужен, но пусть будет валидный пользователь — это ближе к жизни.
    session.add(User(telegram_id=42, username="u", topic_weights="{}"))
    session.commit()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def test_cache_miss_when_empty(db):
    assert _read_recommendation_cache(db, 42, limit=25) is None


def test_cache_write_then_read(db):
    items = [{"event_id": 1, "title": "X"}]
    _write_recommendation_cache(db, 42, 25, items)
    cached = _read_recommendation_cache(db, 42, limit=25)
    assert cached == items


def test_cache_expired_is_miss(db):
    _write_recommendation_cache(db, 42, 25, [{"event_id": 1}])
    # руками сдвигаем expires_at в прошлое
    row = db.query(RecommendationCache).filter_by(telegram_id=42).one()
    row.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
    db.commit()
    assert _read_recommendation_cache(db, 42, limit=25) is None


def test_cache_limit_smaller_than_request_is_miss(db):
    _write_recommendation_cache(db, 42, 5, [{"event_id": 1}])
    # запросили больше, чем в кэше — не возвращаем (вернули бы подрезанный список)
    assert _read_recommendation_cache(db, 42, limit=25) is None


def test_cache_invalidate(db):
    _write_recommendation_cache(db, 42, 25, [{"event_id": 1}])
    invalidate_recommendation_cache(db, 42)
    assert db.query(RecommendationCache).count() == 0
    assert _read_recommendation_cache(db, 42, limit=25) is None


def test_cache_write_overwrites(db):
    _write_recommendation_cache(db, 42, 25, [{"event_id": 1}])
    _write_recommendation_cache(db, 42, 25, [{"event_id": 2}])
    cached = _read_recommendation_cache(db, 42, limit=25)
    assert cached == [{"event_id": 2}]


def test_cache_disabled_by_settings(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "recommendation_cache_enabled", False)
    _write_recommendation_cache(db, 42, 25, [{"event_id": 1}])
    # write — no-op
    assert db.query(RecommendationCache).count() == 0
    # read — None даже если ряд каким-то образом есть
    db.add(RecommendationCache(
        telegram_id=42,
        items_json=json.dumps([{"event_id": 99}]),
        limit_used=25,
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
    ))
    db.commit()
    assert _read_recommendation_cache(db, 42, limit=25) is None
