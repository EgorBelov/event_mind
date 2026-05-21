"""Tests for skill profile + skill-gap scoring."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.event import Event
from app.db.models.user import User
from app.db.models.user_skill_profile import UserSkillProfile
from app.recommender.cold_start import BioProfile
from app.recommender.skill_gap import (
    upsert_skill_profile,
    load_skill_profile,
    compute_skill_gap_score,
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


def _make_event(db, tech, seniority="middle") -> Event:
    e = Event(
        title="X", description="d", format="online", city="any", level="any",
        date="2026-06-01", seniority=seniority,
        tech_stack=json.dumps(tech),
    )
    db.add(e)
    db.flush()
    return e


def test_upsert_and_load_skill_profile(db):
    user = User(telegram_id=1, username="u", preferred_format="online", city="any")
    db.add(user)
    db.flush()
    profile = BioProfile(
        topics=["ai_ml", "backend"], priority_topics=["ai_ml"],
        seniority="middle", goals=["перейти в ML"],
    )
    row = upsert_skill_profile(db, user.id, profile)
    db.commit()

    assert row.target_role == "ml_engineer"
    loaded = load_skill_profile(db, user.id)
    assert "python" in loaded["target_skills"]
    assert "перейти в ML" in loaded["goals"]


def test_skill_gap_nonzero_on_overlap(db):
    e = _make_event(db, ["python", "pytorch", "kubernetes"], seniority="middle")
    profile = {
        "target_skills": ["python", "pytorch", "mlops"],
        "seniority": "middle",
        "current_skills": [],
        "goals": [],
        "target_role": "ml_engineer",
        "current_role": None,
    }
    score = compute_skill_gap_score(profile, e)
    # overlap = 2 / 3 = 0.66 + seniority bonus = ~0.76
    assert 0.6 < score <= 1.0


def test_skill_gap_zero_without_overlap(db):
    e = _make_event(db, ["scala", "kafka"], seniority="middle")
    profile = {"target_skills": ["python", "pytorch"], "seniority": "middle"}
    assert compute_skill_gap_score(profile, e) == 0.0


def test_skill_gap_returns_zero_for_empty_profile(db):
    e = _make_event(db, ["python"])
    assert compute_skill_gap_score(None, e) == 0.0
    assert compute_skill_gap_score({"target_skills": []}, e) == 0.0
