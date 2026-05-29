"""End-to-end test of multi-agent Copilot graph with a mocked LLM."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.event import Event
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
        telegram_id=42, username="u", preferred_format="online", city="any",
        topic_weights=json.dumps({"ai_ml": 3}),
    )
    db.add(user)
    db.flush()
    db.add(UserTopic(user_id=user.id, topic_id=t.id))
    ev = Event(
        title="LLM Workshop", description="d", format="online", city="any", level="any",
        date="2026-06-01", embedding=json.dumps([1.0, 0.0, 0.0]),
    )
    db.add(ev)
    db.flush()
    db.add(EventTopic(event_id=ev.id, topic_id=t.id))
    db.commit()
    return user, ev


class FakeResponse:
    def __init__(self, content): self.content = content
    tool_calls = []


def _make_routed_fake_llm(supervisor_intent: str, specialist_text: str):
    """LLM, который возвращает разные ответы в зависимости от того, какая
    нода его сейчас вызывает. Первый invoke — supervisor (JSON intent),
    дальше — специалист (свободный текст), потом — критик ('OK').
    """
    responses = iter([
        FakeResponse(json.dumps({
            "intent": supervisor_intent, "reasoning": "test",
            "target_event_id": None, "horizon_months": None,
        })),
        FakeResponse(specialist_text),
        FakeResponse("OK"),
        FakeResponse("Ничего нового."),  # safety на лишние вызовы
    ])

    class FakeLLM:
        def invoke(self, msgs): return next(responses)
        def bind_tools(self, tools): return self
    return FakeLLM()


def _invoke_with_retrieve_mock(db, user, goal, fake_llm, monkeypatch):
    """Подменяет LLM и эмбеддер, гоняет полный copilot_graph.invoke."""
    import app.agents.recommendation.llm as llm_mod
    monkeypatch.setattr(llm_mod, "llm", fake_llm)

    import app.recommender.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "embed_text", lambda text: [1.0, 0.0, 0.0])
    monkeypatch.setattr(emb_mod, "ensure_event_embeddings", lambda db, events: 0)

    from app.agents.copilot.agent import copilot_graph
    return copilot_graph.invoke({
        "goal": goal,
        "telegram_id": user.telegram_id,
        "db": db,
        "k": 5,
        "limit": 3,
        "history": [],
    })


def test_supervisor_routes_to_recommendation(db, monkeypatch):
    user, ev = _seed(db)
    fake = _make_routed_fake_llm(
        "recommend",
        f"Подборка:\n- {ev.title}\n\nRECOMMENDED_IDS: [{ev.id}]",
    )
    result = _invoke_with_retrieve_mock(db, user, "посоветуй ивентов", fake, monkeypatch)
    assert result["intent"] == "recommend"
    assert result["specialist"] == "recommendation_specialist"
    assert ev.id in result["recommended_event_ids"]


def test_supervisor_routes_to_career_coach(db, monkeypatch):
    user, ev = _seed(db)
    fake = _make_routed_fake_llm(
        "career",
        "Учи Python, PyTorch, MLOps.",
    )
    result = _invoke_with_retrieve_mock(db, user, "что учить", fake, monkeypatch)
    assert result["intent"] == "career"
    assert result["specialist"] == "career_coach"


def test_supervisor_routes_to_summary(db, monkeypatch):
    user, ev = _seed(db)
    fake = _make_routed_fake_llm("summary", "Ты ничего не лайкал.")
    result = _invoke_with_retrieve_mock(db, user, "что я лайкал?", fake, monkeypatch)
    assert result["intent"] == "summary"
    assert result["specialist"] == "summary_specialist"
    assert result["recommended_event_ids"] == []


def test_supervisor_routes_to_explainer_with_target_id(db, monkeypatch):
    user, ev = _seed(db)

    class FakeResp:
        def __init__(self, content): self.content = content
        tool_calls = []

    responses = iter([
        FakeResp(json.dumps({
            "intent": "explain", "reasoning": "test",
            "target_event_id": ev.id, "horizon_months": None,
        })),
        FakeResp("Объясняю..."),
    ])

    class FakeLLM:
        def invoke(self, msgs): return next(responses)
        def bind_tools(self, tools): return self

    result = _invoke_with_retrieve_mock(db, user, f"почему event #{ev.id}", FakeLLM(), monkeypatch)
    assert result["intent"] == "explain"
    assert result["specialist"] == "event_explainer"
    assert result["target_event_id"] == ev.id


def test_routing_falls_back_to_keyword_when_llm_invalid(db, monkeypatch):
    user, ev = _seed(db)

    class FakeResp:
        def __init__(self, content): self.content = content
        tool_calls = []

    # Supervisor возвращает мусор → keyword fallback → roadmap (по «3 месяца»).
    # Затем планировщик отвечает текстом.
    responses = iter([
        FakeResp("garbage not json"),
        FakeResp(f"Месяц 1\n\nRECOMMENDED_IDS: [{ev.id}]"),
    ])

    class FakeLLM:
        def invoke(self, msgs): return next(responses)
        def bind_tools(self, tools): return self

    result = _invoke_with_retrieve_mock(db, user, "план на 3 месяца ML", FakeLLM(), monkeypatch)
    assert result["intent"] == "roadmap"
    assert result["specialist"] == "roadmap_planner"
