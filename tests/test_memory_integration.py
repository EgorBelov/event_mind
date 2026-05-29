"""Integration tests: memory triggers in create_interaction + cold-start."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.event import Event
from app.db.models.topic import EventTopic, Topic, UserTopic
from app.db.models.user import User
from app.db.models.user_memory import UserMemory


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
        telegram_id=42, username="u", preferred_format="online", city="any",
        topic_weights=json.dumps({"ai_ml": 3}),
    )
    db.add(user)
    db.flush()
    db.add(UserTopic(user_id=user.id, topic_id=t.id))
    ev = Event(
        title="LLM Workshop", description="d", format="online", city="any", level="any",
        date="2026-06-01",
    )
    db.add(ev)
    db.flush()
    db.add(EventTopic(event_id=ev.id, topic_id=t.id))
    db.commit()
    return user, ev


class _FakeResp:
    def __init__(self, content): self.content = content


def _patch_llm(monkeypatch, content):
    class FakeLLM:
        def invoke(self, msgs): return _FakeResp(content)
    import app.agents.recommendation.llm as llm_mod
    monkeypatch.setattr(llm_mod, "llm", FakeLLM())


def test_create_interaction_triggers_memory_extract(db, monkeypatch):
    user, ev = _seed(db)
    _patch_llm(monkeypatch, json.dumps({
        "items": [
            {"text": "Сильный интерес к LLM-практике", "category": "interest", "salience": 7},
        ],
    }))
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [0.1, 0.2, 0.3])

    from app.api.services.recommendation_service import create_interaction
    result = create_interaction(db, user.telegram_id, ev.id, "like")
    assert result["success"] is True

    rows = db.query(UserMemory).filter_by(user_id=user.id).all()
    assert len(rows) == 1
    assert rows[0].source.startswith("interaction:like:event:")
    assert "LLM" in rows[0].text


def test_create_interaction_toggle_does_not_extract_memory(db, monkeypatch):
    """Откат (повторный лайк) не должен порождать новые заметки."""
    user, ev = _seed(db)
    _patch_llm(monkeypatch, json.dumps({
        "items": [{"text": "интерес", "category": "interest", "salience": 7}],
    }))
    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [0.1, 0.2, 0.3])

    from app.api.services.recommendation_service import create_interaction
    create_interaction(db, user.telegram_id, ev.id, "like")
    create_interaction(db, user.telegram_id, ev.id, "like")  # toggle off

    rows = db.query(UserMemory).filter_by(user_id=user.id).all()
    # Только от первого вызова (positive); toggle-off не пишет
    assert len(rows) == 1


def test_memory_disabled_via_settings(db, monkeypatch):
    user, ev = _seed(db)
    _patch_llm(monkeypatch, json.dumps({
        "items": [{"text": "x", "category": "interest", "salience": 9}],
    }))
    from app.core.config import settings
    monkeypatch.setattr(settings, "memory_enabled", False)

    from app.api.services.recommendation_service import create_interaction
    create_interaction(db, user.telegram_id, ev.id, "like")

    assert db.query(UserMemory).count() == 0
