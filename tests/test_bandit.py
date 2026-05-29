"""Tests for LinUCB contextual bandit."""
import json

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.event import Event
from app.db.models.topic import EventTopic, Topic, UserTopic
from app.db.models.user import User
from app.db.models.user_bandit_state import UserBanditState
from app.recommender.bandit import (
    LINUCB_DIM,
    context_vector,
    load_user_bandit,
    ucb_score,
    update_from_feedback,
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
    t = Topic(code="ai_ml", title="AI")
    db.add(t)
    db.flush()
    user = User(
        telegram_id=1, username="u", preferred_format="online", city="moscow",
        topic_weights=json.dumps({"ai_ml": 5}),
    )
    db.add(user)
    db.flush()
    db.add(UserTopic(user_id=user.id, topic_id=t.id))
    ev = Event(
        title="E", description="d", format="online", city="moscow", level="any",
        date="2026-06-01", quality_score=8, hype_score=7,
    )
    db.add(ev)
    db.flush()
    db.add(EventTopic(event_id=ev.id, topic_id=t.id))
    db.commit()
    return user, ev


def test_context_vector_has_expected_dim(db):
    user, ev = _seed(db)
    x = context_vector(user, ev, freshness=0.9)
    assert x.shape == (LINUCB_DIM,)
    # Слот ai_ml должен быть 1.0 (есть и у user, и у event).
    assert x[0] == 1.0
    # format_match (1-я фича после topic-слотов).
    assert x[8] == 1.0


def test_initial_state_yields_zero_mean(db):
    user, ev = _seed(db)
    A, b = load_user_bandit(db, user.id)
    x = context_vector(user, ev, freshness=1.0)
    # Изначально θ=0 → mean=0; UCB > 0 только за счёт exploration.
    score = ucb_score(A, b, x, alpha=1.0)
    assert score > 0.0  # exploration член


def test_update_persists_state(db):
    user, ev = _seed(db)
    x = context_vector(user, ev, freshness=1.0)
    update_from_feedback(db, user.id, x, reward=1.0)
    db.commit()

    row = db.query(UserBanditState).filter_by(user_id=user.id).one()
    assert row.update_count == 1
    A = np.array(json.loads(row.a_json))
    b = np.array(json.loads(row.b_json))
    # После одного апдейта score должен сместиться вверх (mean > 0).
    score_after = ucb_score(A, b, x, alpha=0.0)  # без exploration
    assert score_after > 0.0


def test_positive_reward_increases_mean(db):
    user, ev = _seed(db)
    x = context_vector(user, ev, freshness=1.0)
    A0, b0 = load_user_bandit(db, user.id)
    mean0 = ucb_score(A0, b0, x, alpha=0.0)

    for _ in range(5):
        update_from_feedback(db, user.id, x, reward=1.0)
    db.commit()
    A1, b1 = load_user_bandit(db, user.id)
    mean1 = ucb_score(A1, b1, x, alpha=0.0)
    assert mean1 > mean0
