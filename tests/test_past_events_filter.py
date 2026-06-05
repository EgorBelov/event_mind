"""Тесты фильтра прошедших событий в выдаче.

Принцип: события с `start_at < now() - grace` не должны попадать в
рекомендации/поиск, но БД ничего не удаляет — интеракции на них
остаются для bandit/Bayesian обучения.
"""
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.utils import utcnow_naive
from app.db.base import Base
from app.db.event_filters import upcoming_only
from app.db.models.event import Event


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _make_event(title: str, start_at) -> Event:
    return Event(
        title=title, description="x", format="online",
        city="any", level="any", date=str(start_at or ""),
        start_at=start_at,
    )


def test_filter_drops_past_events(session):
    now = utcnow_naive()
    past = _make_event("Прошлогодний митап", now - timedelta(days=365))
    soon = _make_event("Завтра митап", now + timedelta(days=1))
    session.add_all([past, soon])
    session.commit()

    titles = {e.title for e in upcoming_only(session.query(Event)).all()}
    assert "Завтра митап" in titles
    assert "Прошлогодний митап" not in titles


def test_filter_keeps_null_start_at(session):
    """Событие без start_at не должно выкидываться — источник просто не дал дату."""
    no_date = _make_event("Дата неизвестна", None)
    session.add(no_date)
    session.commit()

    titles = {e.title for e in upcoming_only(session.query(Event)).all()}
    assert "Дата неизвестна" in titles


def test_filter_respects_grace_period(session):
    """Событие, начавшееся 2 часа назад, ещё показывается (грейс 6 часов)."""
    now = utcnow_naive()
    just_started = _make_event("Идёт прямо сейчас", now - timedelta(hours=2))
    long_over = _make_event("Закончился вчера", now - timedelta(hours=24))
    session.add_all([just_started, long_over])
    session.commit()

    titles = {e.title for e in upcoming_only(session.query(Event)).all()}
    assert "Идёт прямо сейчас" in titles
    assert "Закончился вчера" not in titles


def test_filter_grace_override(session):
    """Можно перекрыть грейс-период (например, для дайджеста на следующее утро)."""
    now = utcnow_naive()
    overnight = _make_event("Завершился ночью", now - timedelta(hours=10))
    session.add(overnight)
    session.commit()

    # default grace=6 → не показывается
    titles_default = {e.title for e in upcoming_only(session.query(Event)).all()}
    assert "Завершился ночью" not in titles_default

    # явный grace=24 → показывается
    titles_extended = {
        e.title for e in upcoming_only(session.query(Event), grace_hours=24).all()
    }
    assert "Завершился ночью" in titles_extended


def test_search_excludes_past_events(session):
    """Интеграция: search_events не возвращает прошедшие события."""
    from app.api.services.search_service import search_events

    now = utcnow_naive()
    session.add_all([
        _make_event("Python митап 2020", now - timedelta(days=400)),
        _make_event("Python митап 2030", now + timedelta(days=30)),
    ])
    session.commit()

    results = search_events(session, query="python")
    titles = {r["title"] for r in results}
    assert "Python митап 2030" in titles
    assert "Python митап 2020" not in titles
