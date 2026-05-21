"""Tests for Supervisor agent: intent classification (LLM + keyword fallback) and routing."""
import json

import pytest

from app.agents.copilot.supervisor import (
    SupervisorDecision,
    _keyword_classify,
    _llm_classify,
    supervisor_node,
    route_after_supervisor,
)


# ─── Keyword fallback ────────────────────────────────────────────────────


@pytest.mark.parametrize("goal, expected_intent", [
    ("посоветуй ивентов про AI", "recommend"),
    ("найди что-нибудь по DevOps", "recommend"),
    ("почему ты рекомендовал event #42 вообще", "explain"),
    ("расскажи про ивент 17", "explain"),
    ("что я лайкал последний месяц?", "summary"),
    ("мой профиль и история взаимодействий", "summary"),
    ("составь план на 3 месяца до middle ML", "roadmap"),
    ("обучающий маршрут по DevOps", "roadmap"),
    ("какие скиллы нужны чтобы стать senior backend", "career"),
    ("что учить если хочу перейти в ML", "career"),
])
def test_keyword_classify_matches_expected_intent(goal, expected_intent):
    decision = _keyword_classify(goal)
    assert decision.intent == expected_intent


def test_keyword_classify_default_is_recommend():
    decision = _keyword_classify("случайный неопределённый текст без триггеров")
    assert decision.intent == "recommend"


def test_keyword_classify_extracts_event_id():
    decision = _keyword_classify("почему ты рекомендовал event #777")
    assert decision.intent == "explain"
    assert decision.target_event_id == 777


def test_keyword_classify_extracts_horizon_months():
    decision = _keyword_classify("план на 6 месяцев до middle DevOps")
    assert decision.intent == "roadmap"
    assert decision.horizon_months == 6


# ─── LLM classification (mocked) ─────────────────────────────────────────


def test_llm_classify_parses_valid_json(monkeypatch):
    class FakeResponse:
        content = json.dumps({
            "intent": "career",
            "reasoning": "user asks about target_role",
            "target_event_id": None,
            "horizon_months": None,
        })

    class FakeLLM:
        def invoke(self, msgs): return FakeResponse()

    import app.agents.copilot.supervisor as sup_mod
    import app.agents.recommendation.llm as llm_mod
    monkeypatch.setattr(llm_mod, "llm", FakeLLM())

    decision = _llm_classify("как стать ML engineer", "")
    assert decision is not None
    assert decision.intent == "career"


def test_llm_classify_returns_none_on_invalid_json(monkeypatch):
    class FakeResponse:
        content = "not a json"

    class FakeLLM:
        def invoke(self, msgs): return FakeResponse()

    import app.agents.recommendation.llm as llm_mod
    monkeypatch.setattr(llm_mod, "llm", FakeLLM())

    assert _llm_classify("anything", "") is None


def test_llm_classify_rejects_unknown_intent(monkeypatch):
    class FakeResponse:
        content = json.dumps({"intent": "DELETE_DATABASE", "reasoning": "x"})

    class FakeLLM:
        def invoke(self, msgs): return FakeResponse()

    import app.agents.recommendation.llm as llm_mod
    monkeypatch.setattr(llm_mod, "llm", FakeLLM())
    assert _llm_classify("anything", "") is None


# ─── supervisor_node fallback chain ──────────────────────────────────────


def test_supervisor_node_uses_keyword_fallback_when_llm_fails(monkeypatch):
    class BoomLLM:
        def invoke(self, msgs): raise RuntimeError("no key")

    import app.agents.recommendation.llm as llm_mod
    monkeypatch.setattr(llm_mod, "llm", BoomLLM())

    out = supervisor_node({"goal": "почему ты рекомендовал event #42", "history": []})
    assert out["intent"] == "explain"
    assert out["target_event_id"] == 42


# ─── Routing ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("intent, expected_node", [
    ("recommend", "recommendation_specialist"),
    ("career", "career_coach"),
    ("roadmap", "roadmap_planner"),
    ("explain", "event_explainer"),
    ("summary", "summary_specialist"),
    (None, "recommendation_specialist"),         # default
    ("nonsense", "recommendation_specialist"),   # safety
])
def test_route_after_supervisor(intent, expected_node):
    state = {"intent": intent} if intent is not None else {}
    assert route_after_supervisor(state) == expected_node
