"""Tests for LightGCN-style GNN module (pure numpy)."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.user import User
from app.db.models.event import Event
from app.db.models.interaction import Interaction
from app.db.models.topic import Topic, UserTopic, EventTopic
from app.recommender import gnn as gnn_mod


@pytest.fixture
def db(tmp_path, monkeypatch):
    # перенаправляем npz-кэш во временную папку
    monkeypatch.setattr(gnn_mod, "CACHE_FILE", tmp_path / "gnn.npz")
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    gnn_mod.invalidate_cache()
    session.close()
    Base.metadata.drop_all(engine)


def _seed(db, n_users=3, n_events=4):
    t = Topic(code="ai_ml", title="AI")
    db.add(t)
    db.flush()
    users, events = [], []
    for i in range(n_users):
        u = User(telegram_id=100 + i, username=f"u{i}", preferred_format="online", city="any")
        db.add(u)
        db.flush()
        db.add(UserTopic(user_id=u.id, topic_id=t.id))
        users.append(u)
    for j in range(n_events):
        e = Event(
            title=f"E{j}", description="d", format="online", city="any", level="any",
            date="2026-06-01",
            embedding=json.dumps([1.0 if j == 0 else 0.0, 0.0, 0.0] + [0.0] * 29),
        )
        db.add(e)
        db.flush()
        db.add(EventTopic(event_id=e.id, topic_id=t.id))
        events.append(e)
    # Каждый юзер лайкает первое событие
    for u in users:
        db.add(Interaction(user_id=u.id, event_id=events[0].id, action="like"))
    db.commit()
    return users, events


def test_skipped_on_empty_db(db):
    res = gnn_mod.train_gnn(db)
    assert res["status"] == "skipped"


def test_train_creates_cache(db):
    users, events = _seed(db)
    res = gnn_mod.train_gnn(db, layers=2)
    assert res["status"] == "ok"
    assert res["n_users"] == 3
    assert res["n_events"] == 4


def test_gnn_score_returns_value_after_training(db):
    users, events = _seed(db)
    gnn_mod.train_gnn(db, layers=2)
    score = gnn_mod.gnn_score(users[0], events[0])
    assert isinstance(score, float)
    # Юзер взаимодействовал с events[0] → cosine должна быть положительной
    assert score > 0.0


def test_gnn_score_zero_for_unknown_pair(db, monkeypatch):
    users, events = _seed(db)
    gnn_mod.train_gnn(db, layers=2)

    # Несуществующий event
    class FakeEv:
        id = 9999
    assert gnn_mod.gnn_score(users[0], FakeEv()) == 0.0
