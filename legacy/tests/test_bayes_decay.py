"""Tests for temporal Beta decay in bayesian.load_user_stats."""
from datetime import UTC, datetime, timedelta


def _utcnow():
    return datetime.now(UTC).replace(tzinfo=None)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.db.models.topic import Topic, UserTopic
from app.db.models.user import User
from app.db.models.user_topic_stat import UserTopicStat
from app.recommender.bayesian import PRIOR_ALPHA, PRIOR_BETA, _apply_decay, load_user_stats


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def test_apply_decay_unchanged_for_recent():
    a, b = _apply_decay(5.0, 2.0, _utcnow())
    assert abs(a - 5.0) < 0.01
    assert abs(b - 2.0) < 0.01


def test_apply_decay_pulls_toward_prior_over_time():
    old = _utcnow() - timedelta(days=365)
    a, b = _apply_decay(5.0, 2.0, old)
    assert a < 5.0
    assert b < 2.0
    assert a >= PRIOR_ALPHA
    assert b >= PRIOR_BETA


def test_load_user_stats_applies_decay(db, monkeypatch):
    t = Topic(code="ai_ml", title="AI")
    db.add(t)
    db.flush()
    user = User(telegram_id=1, username="u", preferred_format="online", city="any")
    db.add(user)
    db.flush()
    db.add(UserTopic(user_id=user.id, topic_id=t.id))
    stat = UserTopicStat(user_id=user.id, topic_id=t.id, alpha=5.0, beta=2.0)
    db.add(stat)
    db.flush()
    # Принудительно состарим запись
    stat.updated_at = _utcnow() - timedelta(days=200)
    db.commit()

    # Ускорим decay для теста
    monkeypatch.setattr(settings, "bayes_decay_per_day", 0.99)
    stats = load_user_stats(db, user.id)
    alpha, beta = stats["ai_ml"]
    assert alpha < 5.0
    assert beta < 2.0
