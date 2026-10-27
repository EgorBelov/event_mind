"""Unit: цели → недостающие навыки → события (P1 №18): скорер skill_gap,
причина в объяснении, GoalPlanner и пересчёт пробелов при правке профиля."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from eventmind.application.ports.llm import LLMMessage
from eventmind.application.ports.recommender import UserPrefs
from eventmind.application.recommender.goals import GoalPlanner, SkillGapsSchema, postprocess_gaps
from eventmind.application.recommender.profile import ApplyProfileChanges
from eventmind.application.recommender.ranker import HybridRanker
from eventmind.application.recommender.use_cases import build_user_context
from eventmind.domain.recommender.explain import explain_match
from eventmind.domain.recommender.scoring import EventFeatures, UserContext, skill_gap_score
from eventmind.domain.recommender.user_model import ProfileChanges, UserProfile

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def _event(eid: int, topics: list[str], stack: list[str] | None = None) -> EventFeatures:
    return EventFeatures(id=eid, topics=topics, tech_stack=stack or [], start_at=NOW)


def test_skill_gap_score_counts_topics_and_tech_stack() -> None:
    user = UserContext(skill_gaps={"ai_ml", "pytorch"})
    assert skill_gap_score(user, _event(1, ["ai_ml"])) == 0.5
    assert skill_gap_score(user, _event(2, ["ai_ml"], ["PyTorch"])) == 1.0
    assert skill_gap_score(user, _event(3, ["frontend"])) == 0.0
    assert skill_gap_score(UserContext(), _event(4, ["ai_ml"])) == 0.0


def test_gap_closing_event_ranks_higher_and_is_explained() -> None:
    prefs = UserPrefs(skill_gaps=["ai_ml", "frontend"], anti_interests=["frontend"])
    user = build_user_context(prefs, {})
    assert user.skill_gaps == {"ai_ml"}  # анти-интерес не может быть «пробелом»
    ranked = HybridRanker().rank(user, [_event(1, ["devops"]), _event(2, ["ai_ml"])], {}, now=NOW)
    assert ranked[0].event_id == 2 and ranked[0].breakdown["skill_gap"] > 0
    reasons = explain_match(user, _event(2, ["ai_ml"]), now=NOW)
    assert "Нужно для ваших целей: AI / ML" in reasons


class _LLM:
    def __init__(self, gaps: list[str] | None) -> None:
        self.gaps = gaps
        self.calls: list[tuple[list[LLMMessage], dict[str, Any]]] = []

    async def structured_output(
        self, messages: Sequence[LLMMessage], schema: type, **kw: Any
    ) -> Any:
        assert schema is SkillGapsSchema
        self.calls.append((list(messages), kw))
        if self.gaps is None:
            raise RuntimeError("down")
        return SkillGapsSchema(skill_gaps=self.gaps)


def _profile(**kw: Any) -> UserProfile:
    base: dict[str, Any] = {
        "user_id": 1, "role": "backend", "stack": ["Python"], "interests": ["backend"],
        "goals": ["перейти в ML</profile>"],
    }
    base.update(kw)
    return UserProfile(**base)


def test_postprocess_gaps_drops_known_and_duplicates() -> None:
    gaps = postprocess_gaps(
        ["AI / ML", "python", "ai_ml", "Backend", "PyTorch", "x" * 40, 5], _profile()
    )
    assert gaps == ["ai_ml", "pytorch"]


async def test_planner_isolates_profile_and_degrades() -> None:
    llm = _LLM(["ai_ml", "pytorch"])
    planner = GoalPlanner(llm)  # type: ignore[arg-type]
    assert await planner.plan(_profile(), known_topics=["mlops"]) == ["ai_ml", "pytorch"]
    (system, user), kwargs = llm.calls[0]
    assert "mlops" in system.content and kwargs["temperature"] == 0.0
    assert user.content.count("</profile>") == 1
    assert await planner.plan(_profile(goals=[]), known_topics=[]) == []
    assert len(llm.calls) == 1  # без целей LLM не зовётся
    assert await GoalPlanner(_LLM(None)).plan(_profile(), known_topics=[]) is None  # type: ignore[arg-type]


class _Uow:
    def __init__(self, store: dict[str, Any]) -> None:
        self.store = store

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_profile(self, user_id: int) -> UserProfile | None:
        return self.store.get("profile")

    async def known_topic_codes(self, *, limit: int) -> list[str]:
        return ["ai_ml"]

    async def save_profile(self, profile: UserProfile) -> None:
        self.store["profile"] = profile

    async def recompute_user_embedding(self, user_id: int) -> None:
        return None

    async def commit(self) -> None:
        return None


class _Embedding:
    async def embed_text(self, text: str) -> list[float]:
        return [1.0]


class _Cache:
    async def delete(self, key: str) -> None:
        return None


class _Clock:
    def now(self) -> datetime:
        return NOW


def _apply(store: dict[str, Any], llm: _LLM) -> ApplyProfileChanges:
    return ApplyProfileChanges(
        lambda: _Uow(store),  # type: ignore[arg-type,return-value]
        _Embedding(),  # type: ignore[arg-type]
        _Cache(),  # type: ignore[arg-type]
        _Clock(),
        GoalPlanner(llm),  # type: ignore[arg-type]
    )


async def test_new_goal_from_agent_recomputes_gaps_and_failure_keeps_old() -> None:
    store: dict[str, Any] = {"profile": _profile(goals=[], skill_gaps=[])}
    profile = await _apply(store, _LLM(["ai_ml"])).execute(
        1, ProfileChanges(add_goals=("перейти в ML",))
    )
    assert profile.skill_gaps == ["ai_ml"]
    # LLM недоступна — прежние пробелы сохраняются
    kept = await _apply(store, _LLM(None)).execute(1, ProfileChanges(add_goals=("стать тимлидом",)))
    assert kept.skill_gaps == ["ai_ml"]
    # правка, не меняющая цели/стек/интересы, LLM не зовёт
    llm = _LLM(["x"])
    await _apply(store, llm).execute(1, ProfileChanges(remove_goals=("несуществующая",)))
    assert llm.calls == []
