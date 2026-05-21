"""Tests for Bayesian topic preference model (Beta + Thompson sampling)."""
import random

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.user import User
from app.db.models.event import Event
from app.db.models.topic import Topic, UserTopic, EventTopic
from app.db.models.user_topic_stat import UserTopicStat
from app.recommender.bayesian import (
    update_stats_from_feedback,
    load_user_stats,
    thompson_score,
    posterior_mean,
    PRIOR_ALPHA,
    PRIOR_BETA,
    LIKE_WEIGHT,
    DISLIKE_WEIGHT,
)
from app.api.services.recommendation_service import create_interaction


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

    user = User(telegram_id=111, username="u", preferred_format="online", city="any")
    db.add(user)
    db.flush()
    db.add(UserTopic(user_id=user.id, topic_id=t_ai.id))

    event_ai = Event(title="AI Event", description="d", format="online", city="any", level="any", date="2026-06-01")
    event_be = Event(title="BE Event", description="d", format="online", city="any", level="any", date="2026-06-01")
    db.add_all([event_ai, event_be])
    db.flush()
    db.add(EventTopic(event_id=event_ai.id, topic_id=t_ai.id))
    db.add(EventTopic(event_id=event_be.id, topic_id=t_be.id))
    db.commit()
    return user, event_ai, event_be, t_ai, t_be


def test_update_increments_alpha_on_like(db):
    user, event_ai, _, t_ai, _ = _seed(db)

    update_stats_from_feedback(db, user.id, ["ai_ml"], "like", direction=1)
    db.commit()

    stat = db.query(UserTopicStat).filter_by(user_id=user.id, topic_id=t_ai.id).one()
    assert stat.alpha == PRIOR_ALPHA + LIKE_WEIGHT
    assert stat.beta == PRIOR_BETA


def test_update_increments_beta_on_dislike(db):
    user, _, event_be, _, t_be = _seed(db)

    update_stats_from_feedback(db, user.id, ["backend"], "dislike", direction=1)
    db.commit()

    stat = db.query(UserTopicStat).filter_by(user_id=user.id, topic_id=t_be.id).one()
    assert stat.alpha == PRIOR_ALPHA
    assert stat.beta == PRIOR_BETA + DISLIKE_WEIGHT


def test_update_reverses_with_negative_direction(db):
    user, _, _, t_ai, _ = _seed(db)

    update_stats_from_feedback(db, user.id, ["ai_ml"], "like", direction=1)
    update_stats_from_feedback(db, user.id, ["ai_ml"], "like", direction=-1)
    db.commit()

    stat = db.query(UserTopicStat).filter_by(user_id=user.id, topic_id=t_ai.id).one()
    assert stat.alpha == PRIOR_ALPHA  # вернулись к prior
    assert stat.beta == PRIOR_BETA


def test_unknown_topic_codes_are_silently_ignored(db):
    user, *_ = _seed(db)
    update_stats_from_feedback(db, user.id, ["does_not_exist"], "like")
    db.commit()
    assert db.query(UserTopicStat).count() == 0


def test_load_user_stats_returns_codes(db):
    user, *_ = _seed(db)
    update_stats_from_feedback(db, user.id, ["ai_ml"], "like")
    db.commit()

    stats = load_user_stats(db, user.id)
    assert "ai_ml" in stats
    alpha, beta = stats["ai_ml"]
    assert alpha > PRIOR_ALPHA


def test_thompson_prefers_topic_with_more_likes(db):
    user, *_ = _seed(db)
    # 10 likes по ai_ml, 0 по backend
    for _ in range(10):
        update_stats_from_feedback(db, user.id, ["ai_ml"], "like")
    db.commit()
    stats = load_user_stats(db, user.id)

    rng = random.Random(0)
    ai_wins = 0
    for _ in range(200):
        s_ai = thompson_score(stats, ["ai_ml"], rng=rng)
        s_be = thompson_score(stats, ["backend"], rng=rng)
        if s_ai > s_be:
            ai_wins += 1
    assert ai_wins > 150  # сильное предпочтение, статистически


def test_posterior_mean_is_deterministic(db):
    user, *_ = _seed(db)
    update_stats_from_feedback(db, user.id, ["ai_ml"], "like")
    db.commit()
    stats = load_user_stats(db, user.id)

    pm1 = posterior_mean(stats, ["ai_ml"])
    pm2 = posterior_mean(stats, ["ai_ml"])
    assert pm1 == pm2
    assert pm1 > 0.5  # после лайка posterior сдвинулся вверх


def test_create_interaction_updates_bayesian(db):
    user, event_ai, _, t_ai, _ = _seed(db)

    create_interaction(db, user.telegram_id, event_ai.id, "like")

    stat = db.query(UserTopicStat).filter_by(user_id=user.id, topic_id=t_ai.id).one()
    assert stat.alpha == PRIOR_ALPHA + LIKE_WEIGHT


def test_create_interaction_toggle_reverts_bayesian(db):
    user, event_ai, _, t_ai, _ = _seed(db)

    create_interaction(db, user.telegram_id, event_ai.id, "like")
    create_interaction(db, user.telegram_id, event_ai.id, "like")  # toggle off

    stat = db.query(UserTopicStat).filter_by(user_id=user.id, topic_id=t_ai.id).one()
    assert stat.alpha == PRIOR_ALPHA


def test_create_interaction_dislike_then_like_swaps(db):
    user, event_ai, _, t_ai, _ = _seed(db)

    create_interaction(db, user.telegram_id, event_ai.id, "dislike")
    create_interaction(db, user.telegram_id, event_ai.id, "like")

    stat = db.query(UserTopicStat).filter_by(user_id=user.id, topic_id=t_ai.id).one()
    # после dislike: beta +2; после like: dislike откатывается (-2) и like (+3)
    assert stat.beta == PRIOR_BETA
    assert stat.alpha == PRIOR_ALPHA + LIKE_WEIGHT
