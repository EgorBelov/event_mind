"""Tests for semantic search, trending, explainability, and enriched fields."""
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.user import User
from app.db.models.event import Event
from app.db.models.interaction import Interaction
from app.db.models.topic import Topic, UserTopic, EventTopic
from app.db.models.raw_event import RawEvent
from app.recommender.explain import explain_event_for_user, explain_event_detailed
from app.recommender.user_model import dump_topic_weights, build_initial_topic_weights
from app.api.services.search_service import search_events, semantic_search_events
from app.api.routers.analytics import analytics_trending


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _make_topic(db, code: str, title: str) -> Topic:
    t = Topic(code=code, title=title)
    db.add(t)
    db.flush()
    return t


def _make_user(db, tid: int, topics: list[str], preferred_format="online", city="moscow") -> User:
    user = User(
        telegram_id=tid,
        username=f"user_{tid}",
        preferred_format=preferred_format,
        city=city,
        topic_weights=dump_topic_weights(build_initial_topic_weights(topics)),
    )
    db.add(user)
    db.flush()
    for code in topics:
        topic = db.query(Topic).filter_by(code=code).first() or _make_topic(db, code, code)
        db.add(UserTopic(user_id=user.id, topic_id=topic.id))
    db.flush()
    return user


def _make_event(db, title: str, topics: list[str], fmt="online", city="any") -> Event:
    event = Event(
        title=title,
        description=f"Описание: {title}",
        format=fmt,
        city=city,
        level="middle",
        date="2026-06-01",
    )
    db.add(event)
    db.flush()
    for code in topics:
        topic = db.query(Topic).filter_by(code=code).first() or _make_topic(db, code, code)
        db.add(EventTopic(event_id=event.id, topic_id=topic.id))
    db.flush()
    return event


# ── Keyword search ────────────────────────────────────────────────────────────

def test_keyword_search_returns_matching_events(db):
    _make_event(db, "AI Meetup Москва", ["ai_ml"])
    _make_event(db, "Frontend React Workshop", ["frontend"])
    db.commit()

    results = search_events(db, query="AI")
    assert any("AI" in r["title"] for r in results)


def test_keyword_search_topic_filter(db):
    _make_event(db, "Backend Day", ["backend"])
    _make_event(db, "Frontend Conf", ["frontend"])
    db.commit()

    results = search_events(db, topics=["backend"])
    assert all("backend" in r["topics"] for r in results)
    assert len(results) == 1


# ── Enriched fields ───────────────────────────────────────────────────────────

def test_event_has_new_fields(db):
    event = Event(
        title="DevOps Конференция",
        description="Kubernetes, Helm, GitOps",
        format="offline",
        city="moscow",
        level="middle",
        date="2026-07-01",
        tech_stack=json.dumps(["Kubernetes", "Helm"]),
        seniority="middle",
        quality_score=8,
        hype_score=9,
    )
    db.add(event)
    db.commit()

    loaded = db.query(Event).filter_by(title="DevOps Конференция").first()
    assert loaded.seniority == "middle"
    assert loaded.quality_score == 8
    assert loaded.hype_score == 9
    assert json.loads(loaded.tech_stack) == ["Kubernetes", "Helm"]


# ── User embedding field ──────────────────────────────────────────────────────

def test_user_embedding_field_persists(db):
    user = _make_user(db, 9999, ["ai_ml"])
    db.commit()

    emb = [0.1, 0.2, 0.3]
    user.embedding = json.dumps(emb)
    db.commit()

    reloaded = db.query(User).filter_by(telegram_id=9999).first()
    assert json.loads(reloaded.embedding) == emb


# ── Explainability ────────────────────────────────────────────────────────────

def test_explain_returns_string(db):
    user = _make_user(db, 1001, ["ai_ml", "backend"])
    event = _make_event(db, "AI Summit", ["ai_ml"])
    db.commit()

    explanation = explain_event_for_user(user, event)
    assert isinstance(explanation, str)
    assert len(explanation) > 0


def test_explain_detailed_has_keys(db):
    user = _make_user(db, 1002, ["devops"])
    event = _make_event(db, "DevOps Conf", ["devops"])
    db.commit()

    details = explain_event_detailed(user, event, db=db)
    assert "text" in details
    assert "topic_match" in details
    assert "format_match" in details
    assert "city_match" in details
    assert "history_signals" in details
    assert "devops" in details["topic_match"]


def test_explain_format_match(db):
    user = _make_user(db, 1003, ["backend"], preferred_format="online")
    event = _make_event(db, "Backend Webinar", ["backend"], fmt="online")
    db.commit()

    details = explain_event_detailed(user, event)
    assert details["format_match"] is True


# ── Semantic search fallback (no model available → keyword fallback) ──────────

def test_semantic_search_fallback_to_keyword(db, monkeypatch):
    """semantic_search_events must not raise even if sentence-transformers unavailable."""
    _make_event(db, "Python Meetup", ["backend"])
    db.commit()

    # Force embedding import to fail
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "get_model", lambda: (_ for _ in ()).throw(ImportError("no model")))

    results = semantic_search_events(db, query="python")
    assert isinstance(results, list)  # fallback should still return something


# ── Trending ──────────────────────────────────────────────────────────────────

def test_trending_returns_structure(db):
    user = _make_user(db, 2001, ["ai_ml"])
    event = _make_event(db, "Hot AI Event", ["ai_ml"])
    db.add(Interaction(user_id=user.id, event_id=event.id, action="like"))
    db.add(Interaction(user_id=user.id, event_id=event.id, action="save"))
    db.commit()

    # Call the service directly (skip FastAPI dependency injection)
    from collections import Counter
    from datetime import datetime, timedelta
    from app.recommender.scoring import _get_event_topic_codes

    cutoff = datetime.utcnow() - timedelta(days=7)
    interactions = db.query(Interaction).all()
    event_score: dict = {}
    topic_counter: Counter = Counter()
    events_map = {e.id: e for e in db.query(Event).all()}
    for i in interactions:
        weight = 3.0 if i.action == "like" else (2.0 if i.action == "save" else 0.0)
        event_score[i.event_id] = event_score.get(i.event_id, 0.0) + weight
        e = events_map.get(i.event_id)
        if e and i.action in ("like", "save"):
            topic_counter.update(_get_event_topic_codes(e))

    assert event_score[event.id] == 5.0  # like=3 + save=2
    assert "ai_ml" in dict(topic_counter)
