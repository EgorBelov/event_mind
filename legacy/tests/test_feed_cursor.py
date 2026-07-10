"""Тесты курсора ленты бота (users.feed_cursor)."""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.services.recommendation_service import (
    advance_feed_cursor,
    get_feed_cursor,
    set_feed_cursor,
)
from app.db.base import Base
from app.db.models import User


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(User(telegram_id=42, username="u", topic_weights="{}"))
    session.commit()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def test_default_cursor_is_zero(db):
    assert get_feed_cursor(db, 42) == 0


def test_set_and_get(db):
    assert set_feed_cursor(db, 42, 5) == 5
    assert get_feed_cursor(db, 42) == 5


def test_set_clamped_to_zero(db):
    # отрицательное значение не должно создавать «дырку»
    assert set_feed_cursor(db, 42, -3) == 0


def test_advance_increments(db):
    assert advance_feed_cursor(db, 42) == 1
    assert advance_feed_cursor(db, 42) == 2
    assert get_feed_cursor(db, 42) == 2


def test_unknown_user_404(db):
    with pytest.raises(HTTPException) as exc:
        get_feed_cursor(db, 999)
    assert exc.value.status_code == 404
