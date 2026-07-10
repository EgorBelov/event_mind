"""Tests for RAG retrieval used by Copilot."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.event import Event
from app.db.models.interaction import Interaction
from app.db.models.topic import EventTopic, Topic, UserTopic
from app.db.models.user import User
from app.recommender.retrieval import (
    build_interaction_context,
    retrieve_events_for_query,
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


def _seed(db):
    t_ai = Topic(code="ai_ml", title="AI / ML")
    t_be = Topic(code="backend", title="Backend")
    db.add_all([t_ai, t_be])
    db.flush()

    user = User(
        telegram_id=42,
        username="u",
        preferred_format="online",
        city="any",
        embedding=json.dumps([1.0, 0.0, 0.0]),
    )
    db.add(user)
    db.flush()
    db.add(UserTopic(user_id=user.id, topic_id=t_ai.id))

    # event A — близкий к query/user; event B — далёкий.
    event_a = Event(
        title="LLM agents workshop",
        description="LangGraph tutorial",
        format="online", city="any", level="any", date="2026-06-01",
        embedding=json.dumps([1.0, 0.0, 0.0]),
    )
    event_b = Event(
        title="Database internals",
        description="Postgres deep dive",
        format="online", city="any", level="any", date="2026-06-02",
        embedding=json.dumps([0.0, 1.0, 0.0]),
    )
    db.add_all([event_a, event_b])
    db.flush()
    db.add(EventTopic(event_id=event_a.id, topic_id=t_ai.id))
    db.add(EventTopic(event_id=event_b.id, topic_id=t_be.id))
    db.commit()
    return user, event_a, event_b


def test_retrieve_ranks_semantically_close_first(db, monkeypatch):
    user, event_a, event_b = _seed(db)

    # Мокаем эмбеддинг запроса — указывает в ту же сторону, что у event_a.
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [1.0, 0.0, 0.0])
    monkeypatch.setattr(emb_mod, "ensure_event_embeddings", lambda db, events: 0)

    results = retrieve_events_for_query(db, user, query="want to learn LLMs", k=2)

    assert len(results) == 2
    assert results[0]["id"] == event_a.id  # ближе по вектору
    assert results[1]["id"] == event_b.id
    assert results[0]["_score"] > results[1]["_score"]


def test_retrieve_falls_back_on_embedding_failure(db, monkeypatch):
    user, event_a, event_b = _seed(db)

    import app.recommender.embeddings as emb_mod

    def boom(*args, **kwargs):
        raise RuntimeError("no model")

    monkeypatch.setattr(emb_mod, "embed_text", boom)

    # Запрос содержит слово из event_b — fallback должен поднять его.
    results = retrieve_events_for_query(db, user, query="postgres", k=2)
    assert results[0]["id"] == event_b.id


def test_retrieve_respects_k_limit(db, monkeypatch):
    user, *_ = _seed(db)
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [1.0, 0.0, 0.0])
    monkeypatch.setattr(emb_mod, "ensure_event_embeddings", lambda db, events: 0)

    results = retrieve_events_for_query(db, user, query="x", k=1)
    assert len(results) == 1


def test_retrieve_returns_empty_when_no_events(db, monkeypatch):
    # пользователь без событий
    user = User(telegram_id=99, username="x", preferred_format="online", city="any")
    db.add(user)
    db.commit()
    results = retrieve_events_for_query(db, user, query="anything", k=5)
    assert results == []


def test_build_interaction_context_empty(db):
    user, *_ = _seed(db)
    ctx = build_interaction_context(db, user)
    assert ctx == {"summary": "нет истории", "liked": [], "disliked": [], "saved": []}


def test_build_interaction_context_categorizes(db):
    user, event_a, event_b = _seed(db)
    db.add(Interaction(user_id=user.id, event_id=event_a.id, action="like"))
    db.add(Interaction(user_id=user.id, event_id=event_b.id, action="dislike"))
    db.commit()

    ctx = build_interaction_context(db, user)
    assert "лайков 1" in ctx["summary"]
    assert "дизлайков 1" in ctx["summary"]
    assert any(item["title"] == event_a.title for item in ctx["liked"])
    assert any(item["title"] == event_b.title for item in ctx["disliked"])


def test_build_interaction_context_caps_at_max_items(db):
    user, event_a, _ = _seed(db)
    for _ in range(20):
        db.add(Interaction(user_id=user.id, event_id=event_a.id, action="like"))
    db.commit()

    ctx = build_interaction_context(db, user, max_items=5)
    assert len(ctx["liked"]) == 5
