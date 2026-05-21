"""Tests for individual Copilot specialists (с моками LLM)."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.user import User
from app.db.models.event import Event
from app.db.models.interaction import Interaction
from app.db.models.topic import Topic, UserTopic, EventTopic


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
        date="2026-06-01", embedding=json.dumps([1.0, 0.0, 0.0]),
        tech_stack=json.dumps(["python", "pytorch"]),
    )
    db.add(ev)
    db.flush()
    db.add(EventTopic(event_id=ev.id, topic_id=t.id))
    db.commit()
    return user, ev


class FakeLLMResponse:
    def __init__(self, content): self.content = content
    tool_calls = []


def _make_fake_llm(content: str):
    class FakeLLM:
        def invoke(self, msgs): return FakeLLMResponse(content)
        def bind_tools(self, tools): return self
    return FakeLLM()


def _state(db, user, ev, *, goal: str, history=None) -> dict:
    return {
        "goal": goal,
        "telegram_id": user.telegram_id,
        "db": db,
        "limit": 3,
        "history": history or [],
        "user_profile": {
            "topics": ["ai_ml"],
            "preferred_format": "online",
            "city": "any",
        },
        "events": [{"id": ev.id, "title": ev.title}],
        "interaction_context": {"summary": "лайков 0", "liked": [], "saved": [], "disliked": []},
        "tool_calls_log": [],
    }


# ─── Recommendation ──────────────────────────────────────────────────────


def test_recommendation_specialist_returns_answer_and_ids(db, monkeypatch):
    user, ev = _seed(db)
    fake_plan = f"Вот подборка:\n- {ev.title} полезен.\n\nRECOMMENDED_IDS: [{ev.id}]"

    # Critic возвращает "OK" → revise не вызывается.
    responses = iter([FakeLLMResponse(fake_plan), FakeLLMResponse("OK")])

    class FakeLLM:
        def invoke(self, msgs): return next(responses)
        def bind_tools(self, tools): return self

    import app.agents.recommendation.llm as llm_mod
    monkeypatch.setattr(llm_mod, "llm", FakeLLM())

    from app.agents.copilot.specialists.recommendation import recommendation_specialist_node
    out = recommendation_specialist_node(_state(db, user, ev, goal="посоветуй ивентов"))
    assert out["specialist"] == "recommendation_specialist"
    assert ev.id in out["recommended_event_ids"]
    assert "RECOMMENDED_IDS" not in out["answer"]


def test_recommendation_specialist_runs_revise_on_critique(db, monkeypatch):
    user, ev = _seed(db)
    initial = f"Вариант 1\nRECOMMENDED_IDS: [{ev.id}]"
    critique = "Слишком мало разнообразия."
    revised = f"Вариант 2 с разнообразием\nRECOMMENDED_IDS: [{ev.id}]"
    responses = iter([
        FakeLLMResponse(initial),
        FakeLLMResponse(critique),
        FakeLLMResponse(revised),
    ])

    class FakeLLM:
        def invoke(self, msgs): return next(responses)
        def bind_tools(self, tools): return self

    import app.agents.recommendation.llm as llm_mod
    monkeypatch.setattr(llm_mod, "llm", FakeLLM())

    from app.agents.copilot.specialists.recommendation import recommendation_specialist_node
    out = recommendation_specialist_node(_state(db, user, ev, goal="посоветуй"))
    assert "Вариант 2" in out["answer"]


# ─── Career coach ────────────────────────────────────────────────────────


def test_career_coach_returns_no_ids_when_only_advising(db, monkeypatch):
    user, ev = _seed(db)
    fake = "Учить нужно X, Y, Z. Roadmap такой..."  # без RECOMMENDED_IDS

    import app.agents.recommendation.llm as llm_mod
    monkeypatch.setattr(llm_mod, "llm", _make_fake_llm(fake))

    from app.agents.copilot.specialists.career_coach import career_coach_node
    out = career_coach_node(_state(db, user, ev, goal="что учить чтобы стать ML"))
    assert out["specialist"] == "career_coach"
    assert out["recommended_event_ids"] == []
    assert "Учить нужно" in out["answer"]


def test_career_coach_passes_ids_when_present(db, monkeypatch):
    user, ev = _seed(db)
    fake = f"Этот ивент закроет gap в pytorch.\n\nRECOMMENDED_IDS: [{ev.id}]"

    import app.agents.recommendation.llm as llm_mod
    monkeypatch.setattr(llm_mod, "llm", _make_fake_llm(fake))

    from app.agents.copilot.specialists.career_coach import career_coach_node
    out = career_coach_node(_state(db, user, ev, goal="как закрыть skill-gap в ML"))
    assert ev.id in out["recommended_event_ids"]


# ─── Roadmap ─────────────────────────────────────────────────────────────


def test_roadmap_planner_returns_structured_answer(db, monkeypatch):
    user, ev = _seed(db)
    fake = f"Месяц 1: основы\n- {ev.title}\n\nRECOMMENDED_IDS: [{ev.id}]"

    import app.agents.recommendation.llm as llm_mod
    monkeypatch.setattr(llm_mod, "llm", _make_fake_llm(fake))

    from app.agents.copilot.specialists.roadmap import roadmap_planner_node
    state = _state(db, user, ev, goal="составь план на 3 месяца")
    state["horizon_months"] = 3
    out = roadmap_planner_node(state)
    assert out["specialist"] == "roadmap_planner"
    assert "Месяц 1" in out["answer"]
    assert ev.id in out["recommended_event_ids"]


# ─── Event explainer ─────────────────────────────────────────────────────


def test_event_explainer_uses_target_event_id(db, monkeypatch):
    user, ev = _seed(db)
    fake = f"Это событие подходит, потому что..."

    import app.agents.recommendation.llm as llm_mod
    monkeypatch.setattr(llm_mod, "llm", _make_fake_llm(fake))

    from app.agents.copilot.specialists.explainer import event_explainer_node
    state = _state(db, user, ev, goal="почему ты рекомендовал event #999")
    state["target_event_id"] = ev.id
    out = event_explainer_node(state)
    assert out["specialist"] == "event_explainer"
    assert out["recommended_event_ids"] == []
    assert "событие" in out["answer"].lower()


def test_event_explainer_fallback_regex_extracts_id(db, monkeypatch):
    user, ev = _seed(db)
    fake = "Объяснение"

    import app.agents.recommendation.llm as llm_mod
    monkeypatch.setattr(llm_mod, "llm", _make_fake_llm(fake))

    from app.agents.copilot.specialists.explainer import event_explainer_node, _fallback_extract_event_id
    state = _state(db, user, ev, goal=f"расскажи про event #{ev.id}")
    state["target_event_id"] = None
    assert _fallback_extract_event_id(state["goal"], state) == ev.id
    out = event_explainer_node(state)
    assert out["specialist"] == "event_explainer"


# ─── Summary ─────────────────────────────────────────────────────────────


def test_summary_specialist_returns_no_ids(db, monkeypatch):
    user, ev = _seed(db)
    db.add(Interaction(user_id=user.id, event_id=ev.id, action="like"))
    db.commit()

    fake = "Ты лайкнул 1 событие про AI."

    import app.agents.recommendation.llm as llm_mod
    monkeypatch.setattr(llm_mod, "llm", _make_fake_llm(fake))

    from app.agents.copilot.specialists.summary import summary_specialist_node
    out = summary_specialist_node(_state(db, user, ev, goal="что я лайкал?"))
    assert out["specialist"] == "summary_specialist"
    assert out["recommended_event_ids"] == []
    assert "лайкнул" in out["answer"].lower()
