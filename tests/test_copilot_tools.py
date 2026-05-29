"""Tests for Copilot tool-dispatch (без LLM)."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.copilot.tools import TOOL_DEFINITIONS, dispatch_tool
from app.db.base import Base
from app.db.models.event import Event
from app.db.models.interaction import Interaction
from app.db.models.topic import EventTopic, Topic, UserTopic
from app.db.models.user import User


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
    t = Topic(code="ai_ml", title="AI")
    db.add(t)
    db.flush()
    user = User(
        telegram_id=42, username="u", preferred_format="online", city="moscow",
        topic_weights=json.dumps({"ai_ml": 3}),
    )
    db.add(user)
    db.flush()
    db.add(UserTopic(user_id=user.id, topic_id=t.id))
    ev = Event(
        title="LLM workshop", description="d", format="online", city="any", level="any",
        date="2026-06-01", embedding=json.dumps([1.0, 0.0, 0.0]),
    )
    db.add(ev)
    db.flush()
    db.add(EventTopic(event_id=ev.id, topic_id=t.id))
    db.commit()
    return user, ev


def test_tool_definitions_have_required_fields():
    for tool in TOOL_DEFINITIONS:
        assert tool["type"] == "function"
        f = tool["function"]
        assert "name" in f and "description" in f and "parameters" in f


def test_dispatch_get_user_profile(db):
    user, _ = _seed(db)
    result = dispatch_tool("get_user_profile", {}, db=db, telegram_id=42)
    assert "topics" in result
    assert result["preferred_format"] == "online"


def test_dispatch_get_interactions_summary(db):
    user, ev = _seed(db)
    db.add(Interaction(user_id=user.id, event_id=ev.id, action="like"))
    db.commit()
    result = dispatch_tool("get_interactions_summary", {}, db=db, telegram_id=42)
    assert result["likes"] == 1


def test_dispatch_mark_saved_creates_interaction(db):
    user, ev = _seed(db)
    result = dispatch_tool("mark_saved", {"event_id": ev.id}, db=db, telegram_id=42)
    assert result.get("success") is True


def test_dispatch_unknown_tool(db):
    _seed(db)
    result = dispatch_tool("nonexistent", {}, db=db, telegram_id=42)
    assert "error" in result


def test_dispatch_search_events(db, monkeypatch):
    user, ev = _seed(db)
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [1.0, 0.0, 0.0])
    monkeypatch.setattr(emb_mod, "ensure_event_embeddings", lambda db, events: 0)

    result = dispatch_tool("search_events", {"query": "LLM", "k": 1}, db=db, telegram_id=42)
    assert result["count"] >= 1
