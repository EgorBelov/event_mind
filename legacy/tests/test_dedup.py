"""Tests for semantic deduplication."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.event import Event
from app.recommender.dedup import find_semantic_duplicate


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def test_finds_duplicate_above_threshold(db, monkeypatch):
    e = Event(
        title="LLM Meetup", description="d", format="online", city="any", level="any",
        date="2026-06-01", embedding=json.dumps([1.0, 0.0, 0.0]),
    )
    db.add(e)
    db.commit()
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [0.99, 0.01, 0.0])

    dup = find_semantic_duplicate(db, "Some other text with same theme")
    assert dup is not None
    assert dup.id == e.id


def test_returns_none_below_threshold(db, monkeypatch):
    e = Event(
        title="Postgres internals", description="d", format="online", city="any", level="any",
        date="2026-06-01", embedding=json.dumps([1.0, 0.0, 0.0]),
    )
    db.add(e)
    db.commit()
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [0.0, 1.0, 0.0])  # orthogonal

    assert find_semantic_duplicate(db, "anything") is None


def test_returns_none_when_no_events_with_embedding(db, monkeypatch):
    e = Event(
        title="No emb", description="d", format="online", city="any", level="any",
        date="2026-06-01", embedding=None,
    )
    db.add(e)
    db.commit()
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [1.0, 0.0, 0.0])

    assert find_semantic_duplicate(db, "x") is None


def test_skips_when_disabled(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "dedup_enabled", False)
    assert find_semantic_duplicate(db, "x") is None
