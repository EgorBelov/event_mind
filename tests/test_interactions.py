"""Tests for interaction logic using in-memory SQLite."""
import json
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import User, Event, Interaction, Topic, UserTopic, EventTopic
from app.api.services.recommendation_service import create_interaction


@pytest.fixture(scope="function")
def db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def user_and_event(db):
    topic = Topic(code="ai_ml", title="AI / ML")
    db.add(topic)
    db.flush()

    user = User(
        telegram_id=12345,
        username="tester",
        preferred_format="online",
        city="any",
        topic_weights=json.dumps({"ai_ml": 3}),
    )
    db.add(user)
    db.flush()

    user_topic = UserTopic(user_id=user.id, topic_id=topic.id)
    db.add(user_topic)

    event = Event(
        title="Test Event",
        description="A test event",
        format="online",
        city="any",
        level="beginner",
        date="2026-06-01 18:00",
    )
    db.add(event)
    db.flush()

    event_topic = EventTopic(event_id=event.id, topic_id=topic.id)
    db.add(event_topic)

    db.commit()
    return user, event


def test_like_creates_interaction(db, user_and_event):
    user, event = user_and_event
    result = create_interaction(db, user.telegram_id, event.id, "like")
    assert result["success"] is True

    interactions = db.query(Interaction).filter(
        Interaction.user_id == user.id,
        Interaction.event_id == event.id,
        Interaction.action == "like",
    ).all()
    assert len(interactions) == 1


def test_like_and_dislike_are_mutually_exclusive(db, user_and_event):
    user, event = user_and_event

    # Like first
    create_interaction(db, user.telegram_id, event.id, "like")

    # Then dislike — should remove like and add dislike
    create_interaction(db, user.telegram_id, event.id, "dislike")

    likes = db.query(Interaction).filter(
        Interaction.user_id == user.id,
        Interaction.event_id == event.id,
        Interaction.action == "like",
    ).count()
    dislikes = db.query(Interaction).filter(
        Interaction.user_id == user.id,
        Interaction.event_id == event.id,
        Interaction.action == "dislike",
    ).count()

    assert likes == 0
    assert dislikes == 1


def test_dislike_and_like_are_mutually_exclusive(db, user_and_event):
    user, event = user_and_event

    create_interaction(db, user.telegram_id, event.id, "dislike")
    create_interaction(db, user.telegram_id, event.id, "like")

    dislikes = db.query(Interaction).filter(
        Interaction.user_id == user.id,
        Interaction.event_id == event.id,
        Interaction.action == "dislike",
    ).count()
    likes = db.query(Interaction).filter(
        Interaction.user_id == user.id,
        Interaction.event_id == event.id,
        Interaction.action == "like",
    ).count()

    assert dislikes == 0
    assert likes == 1


def test_save_toggle(db, user_and_event):
    user, event = user_and_event

    # First save
    result1 = create_interaction(db, user.telegram_id, event.id, "save")
    assert result1["success"] is True
    assert "saved" in result1["message"]

    saves = db.query(Interaction).filter(
        Interaction.user_id == user.id,
        Interaction.event_id == event.id,
        Interaction.action == "save",
    ).count()
    assert saves == 1

    # Second save = unsave (toggle off)
    result2 = create_interaction(db, user.telegram_id, event.id, "save")
    assert result2["success"] is True
    assert "removed" in result2["message"]

    saves_after = db.query(Interaction).filter(
        Interaction.user_id == user.id,
        Interaction.event_id == event.id,
        Interaction.action == "save",
    ).count()
    assert saves_after == 0


def test_like_toggle(db, user_and_event):
    user, event = user_and_event

    # Like
    create_interaction(db, user.telegram_id, event.id, "like")

    # Like again = remove like
    result = create_interaction(db, user.telegram_id, event.id, "like")
    assert "removed" in result["message"]

    likes = db.query(Interaction).filter(
        Interaction.user_id == user.id,
        Interaction.event_id == event.id,
        Interaction.action == "like",
    ).count()
    assert likes == 0
