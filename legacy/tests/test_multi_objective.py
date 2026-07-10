"""Multi-objective scoring, MMR diversity, freshness, breakdown."""
import json
from datetime import UTC, datetime, timedelta


def _utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.event import Event
from app.db.models.topic import EventTopic, Topic, UserTopic
from app.db.models.user import User
from app.recommender.diversity import mmr_rerank
from app.recommender.hybrid import (
    _parse_event_date,
    compute_score_breakdown,
    freshness_score,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _seed(db, embedding_a=None, embedding_b=None):
    t_ai = Topic(code="ai_ml", title="AI / ML")
    db.add(t_ai)
    db.flush()
    user = User(
        telegram_id=42, username="u", preferred_format="online", city="any",
        topic_weights=json.dumps({"ai_ml": 3}),
        embedding=json.dumps([1.0, 0.0, 0.0]),
    )
    db.add(user)
    db.flush()
    db.add(UserTopic(user_id=user.id, topic_id=t_ai.id))

    event_a = Event(
        title="A", description="d", format="online", city="any", level="any",
        date="2026-06-01",
        quality_score=8, hype_score=9,
        embedding=json.dumps(embedding_a or [1.0, 0.0, 0.0]),
    )
    event_b = Event(
        title="B", description="d", format="online", city="any", level="any",
        date="2026-06-02",
        quality_score=3, hype_score=1,
        embedding=json.dumps(embedding_b or [0.0, 1.0, 0.0]),
    )
    db.add_all([event_a, event_b])
    db.flush()
    db.add(EventTopic(event_id=event_a.id, topic_id=t_ai.id))
    db.add(EventTopic(event_id=event_b.id, topic_id=t_ai.id))
    db.commit()
    return user, event_a, event_b


def test_breakdown_has_all_components(db):
    user, event_a, _ = _seed(db)
    bd = compute_score_breakdown(user, event_a, db=db)
    for key in ("rule", "cosine", "bayesian", "quality", "hype", "freshness", "skill_gap", "bandit", "gnn"):
        assert key in bd


def test_quality_pushes_score_higher(db):
    user, event_a, event_b = _seed(db)
    a = compute_score_breakdown(user, event_a, db=db)
    b = compute_score_breakdown(user, event_b, db=db)
    assert a["quality"] > b["quality"]
    assert a["hype"] > b["hype"]


def test_freshness_decay_monotonic(db):
    now = _utcnow()
    near = freshness_score(now)
    far = freshness_score(now + timedelta(days=365))
    assert near > far
    assert 0.0 <= far < near <= 1.0


def test_parse_event_date_formats():
    assert _parse_event_date("2026-06-01") is not None
    assert _parse_event_date("2026-06-01 18:30") is not None
    assert _parse_event_date("01.06.2026") is not None
    assert _parse_event_date(None) is None
    assert _parse_event_date("not a date") is None


def test_mmr_diversifies_similar_events(db):
    # Два идентичных по эмбеддингу события — MMR должен раздвинуть их в ранге.
    user, event_a, event_b = _seed(db, embedding_a=[1.0, 0.0, 0.0], embedding_b=[1.0, 0.0, 0.0])
    fake_results = [
        {"event_id": event_a.id, "score": 10.0},
        {"event_id": event_b.id, "score": 9.99},
    ]
    # При lambda=1.0 — порядок сохраняется (чистый relevance).
    pure = mmr_rerank(fake_results, db, lambda_=1.0)
    assert [r["event_id"] for r in pure] == [event_a.id, event_b.id]

    # При lambda=0 — фокус на diversity; первое остаётся, второй
    # выбирается ровно потому, что он единственный оставшийся.
    diverse = mmr_rerank(fake_results, db, lambda_=0.0)
    assert {r["event_id"] for r in diverse} == {event_a.id, event_b.id}


def test_mmr_with_missing_embeddings_falls_through(db):
    """Если у событий нет эмбеддингов — MMR не падает, просто возвращает порядок."""
    user, _, _ = _seed(db)
    # Создаём свежее событие без embedding
    e = Event(title="C", description="d", format="online", city="any", level="any", date="2026-06-03")
    db.add(e)
    db.commit()
    fake = [{"event_id": e.id, "score": 5.0}]
    out = mmr_rerank(fake, db, lambda_=0.7)
    assert len(out) == 1
