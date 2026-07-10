"""Tests for LLM cold-start bootstrap."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.topic import Topic
from app.db.models.user import User
from app.db.models.user_topic_stat import UserTopicStat
from app.recommender.cold_start import BioProfile, apply_cold_start


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def test_apply_cold_start_sets_weights_and_bayes(db):
    Topic(code="ai_ml", title="AI")
    db.add(Topic(code="ai_ml", title="AI"))
    db.add(Topic(code="backend", title="Backend"))
    db.flush()
    user = User(telegram_id=1, username="u", preferred_format="any", city="any")
    db.add(user)
    db.flush()

    profile = BioProfile(
        topics=["ai_ml", "backend"],
        priority_topics=["ai_ml"],
        preferred_format="online",
        city="moscow",
        seniority="middle",
        goals=["перейти в ML"],
    )
    applied = apply_cold_start(db, user, profile)

    assert applied["topics_added"] == 2
    assert applied["bayes_updates"] == 1

    weights = json.loads(user.topic_weights)
    assert weights["ai_ml"] >= 5  # priority подкачан
    assert user.preferred_format == "online"
    assert user.city == "moscow"

    stats = db.query(UserTopicStat).filter(UserTopicStat.user_id == user.id).all()
    assert len(stats) == 1  # один — по приоритетной теме


def test_apply_cold_start_skips_format_if_any(db):
    db.add(Topic(code="ai_ml", title="AI"))
    db.flush()
    user = User(telegram_id=2, username="u", preferred_format="hybrid", city="spb")
    db.add(user)
    db.flush()

    profile = BioProfile(
        topics=["ai_ml"], priority_topics=[], preferred_format="any", city=None,
    )
    apply_cold_start(db, user, profile)
    # preferred_format=="any" не должно перезатереть существующий 'hybrid'
    assert user.preferred_format == "hybrid"
    assert user.city == "spb"
