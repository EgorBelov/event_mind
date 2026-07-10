"""Прямой тест главного hot-path'а: get_recommendations_for_user.

Тест намеренно минималистичен по моку зависимостей — реальный scoring
(rule + cosine + bayesian + ...) тяжёл и зависит от sentence-transformers.
Здесь:
- кладём 3 простых события и 1 пользователя на SQLite-памяти;
- стабим embedding-функции, чтобы тест не грузил MiniLM;
- проверяем главные инварианты: возвращается list, ограничивается limit'ом,
  кэш заполняется и используется на повторе, серия схлопывается.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.services.recommendation_service import (
    get_recommendations_for_user,
    invalidate_recommendation_cache,
)
from app.db.base import Base
from app.db.models import Event, EventTopic, RecommendationCache, Topic, User, UserTopic


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def stub_embeddings(monkeypatch):
    monkeypatch.setattr(
        "app.recommender.embeddings.build_rich_user_embedding",
        lambda u, interactions=None: [0.1] * 4,
    )
    monkeypatch.setattr(
        "app.recommender.embeddings.build_event_embedding",
        lambda e: [0.1] * 4,
    )
    monkeypatch.setattr(
        "app.recommender.embeddings.build_session_embedding",
        lambda db, u, window=5: None,
    )


@pytest.fixture
def seed(db):
    topic = Topic(code="ai_ml", title="AI / ML")
    db.add(topic)
    db.flush()

    user = User(
        telegram_id=42, username="hot",
        preferred_format="online", city="any",
        topic_weights=json.dumps({"ai_ml": 5}),
    )
    db.add(user)
    db.flush()
    db.add(UserTopic(user_id=user.id, topic_id=topic.id))

    # 3 события одной серии + 1 уникальное
    series_events = [
        Event(
            title=f"Python MeetUp #{i}",
            description="d", format="online", city="any", level="any",
            date="2026-06-01", series_slug="python-meetup",
        )
        for i in range(3)
    ]
    other = Event(
        title="Backend Architecture", description="d", format="online",
        city="any", level="any", date="2026-06-15",
    )
    db.add_all([*series_events, other])
    db.flush()
    for ev in [*series_events, other]:
        db.add(EventTopic(event_id=ev.id, topic_id=topic.id))
    db.commit()
    return user


def test_returns_list_and_respects_limit(db, stub_embeddings, seed):
    res = get_recommendations_for_user(db, seed.telegram_id, limit=2)
    assert isinstance(res, list)
    assert len(res) <= 2


def test_series_collapses_to_single(db, stub_embeddings, seed):
    res = get_recommendations_for_user(db, seed.telegram_id, limit=10)
    titles = [r["title"] for r in res]
    # Анти-флуд: из 3 «Python MeetUp #N» оставлен один
    python_count = sum(1 for t in titles if "Python MeetUp" in t)
    assert python_count == 1


def test_cache_populated_after_call(db, stub_embeddings, seed):
    assert db.query(RecommendationCache).count() == 0
    get_recommendations_for_user(db, seed.telegram_id, limit=5)
    rows = db.query(RecommendationCache).all()
    assert len(rows) == 1
    assert rows[0].telegram_id == seed.telegram_id


def test_cache_hit_skips_scoring(db, stub_embeddings, seed, monkeypatch):
    """Повторный вызов должен взять из кэша — не дёргать компоненты скоринга."""
    get_recommendations_for_user(db, seed.telegram_id, limit=5)

    # Подменяем дорогостоящую функцию и ловим её вызовы. Кэш-hit её не должен трогать.
    calls = {"n": 0}

    def _spy(*a, **kw):
        calls["n"] += 1
        return {}

    monkeypatch.setattr(
        "app.recommender.hybrid.compute_score_breakdown", _spy
    )
    res = get_recommendations_for_user(db, seed.telegram_id, limit=5)
    assert isinstance(res, list)
    assert calls["n"] == 0


def test_invalidate_then_recompute(db, stub_embeddings, seed):
    get_recommendations_for_user(db, seed.telegram_id, limit=5)
    invalidate_recommendation_cache(db, seed.telegram_id)
    assert db.query(RecommendationCache).count() == 0
    # Следующий вызов снова создаст запись.
    get_recommendations_for_user(db, seed.telegram_id, limit=5)
    assert db.query(RecommendationCache).count() == 1


def test_unknown_user_raises_404(db, stub_embeddings):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        get_recommendations_for_user(db, 999, limit=5)
    assert exc.value.status_code == 404
