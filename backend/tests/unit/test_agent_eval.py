"""Unit: оценка агента (A6) — набор вызовов инструментов, метрики, «мир» в
памяти и симуляция диалога на фейковых LLM (без сети, БД и torch)."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from eval.agent.simulate import (
    PersonaRun,
    TurnLog,
    UserSimulator,
    run_cold,
    run_dialog,
    run_form,
    summarize,
    turns_to_hit,
    unjudged_pairs,
)
from eval.agent.toolcalls import (
    ToolCase,
    check_constraint,
    load_dataset,
    run_toolcalls,
    score_case,
)
from eval.agent.world import USER_ID, QueryEmbedding, World, build_stack
from eval.real.data import Persona

from eventmind.application.agent.tools import ALL_TOOLS
from eventmind.application.ports.llm import (
    LLMMessage,
    LLMResult,
    LLMUsage,
    ToolCall,
    ToolSpec,
    ToolStep,
)
from eventmind.application.ports.search import SearchQuery
from eventmind.application.recommender.profile_extractor import ExtractedProfileSchema
from eventmind.domain.events.entities import Event

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


# ── набор вызовов инструментов ────────────────────────────────────────────────
def test_dataset_is_consistent() -> None:
    dataset = load_dataset()
    names = {tool.name for tool in ALL_TOOLS} | {None}
    assert len(dataset.cases) >= 30
    assert len({c.id for c in dataset.cases}) == len(dataset.cases)
    assert all(set(c.tools) <= names for c in dataset.cases)
    # «второе», «первое» ссылаются на показанные в контексте события
    shown = {ev["id"] for ev in dataset.shown}
    assert all(c.args.get("event_id") in shown for c in dataset.cases if "event_id" in c.args)


def test_check_constraint_variants() -> None:
    args = {"city": "Пермь", "topics": ["AI / ML", "go"], "add_goals": ["  "], "format": "online"}
    assert check_constraint("city", "perm", args)
    assert check_constraint("city", "spb|perm", args)
    assert not check_constraint("city", "moscow", args)
    assert check_constraint("topics_any", ["ai_ml", "ml"], args)
    assert not check_constraint("topics_any", ["devops"], args)
    assert check_constraint("format", "ONLINE", args)
    assert not check_constraint("event_type", "meetup", args)
    assert not check_constraint("present", ["add_goals"], args)  # только пробелы
    assert check_constraint("present", ["add_goals|topics"], args)


def test_score_case() -> None:
    case = ToolCase(id="x", message="", tools=["search_events"], args={"city": "perm"})
    assert score_case(case, "search_events", {"city": "perm"}) == (True, 1, 1)
    assert score_case(case, "recommend", {}) == (False, 0, 1)
    chit = ToolCase(id="n", message="", tools=[None])
    assert score_case(chit, None, {}) == (True, 0, 0)


class OneStepLLM:
    """Отвечает вызовом по ключевому слову реплики — для проверки подсчёта."""

    async def complete_with_tools(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolSpec],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ToolStep:
        assert messages[0].role == "system" and "Сегодня 2026-10-27" in messages[0].content
        assert {t.name for t in tools} == {t.name for t in ALL_TOOLS}
        text = messages[-1].content
        if "Перми" in text or "Пермь" in text:
            call = ToolCall(id="1", name="update_settings", arguments={"city": "perm"})
            return ToolStep(text="", tool_calls=(call,), provider="fake")
        return ToolStep(text="не знаю", tool_calls=(), provider="fake")


async def test_run_toolcalls_summarizes() -> None:
    report = await run_toolcalls(OneStepLLM(), load_dataset())
    assert report.n == len(load_dataset().cases)
    assert report.per_tool["update_settings"] > 0  # «Я переехал в Пермь»
    assert report.per_tool["∅"] == 1.0  # болтовня без инструмента
    assert report.confusion["search_events"] == {"∅": 12}
    assert 0 < report.tool_accuracy < 1 and report.errors == 0


# ── мир в памяти ──────────────────────────────────────────────────────────────
def _event(eid: int, topics: list[str], vec: list[float], *, days: int = 3, city: str = "moscow",
           fmt: str = "offline", quality: int = 5) -> Event:
    return Event(
        id=eid, source="t", title=f"Событие {eid}", description=f"про {' '.join(topics)}",
        format=fmt, city=city, level="any", date="", start_at=NOW + timedelta(days=days),
        topics=topics, embedding=vec, quality_score=quality,
    )


EVENTS = [
    _event(1, ["golang"], [1.0, 0.0], quality=4),
    _event(2, ["frontend"], [0.0, 1.0], quality=9),
    _event(3, ["golang", "highload"], [0.9, 0.1], city="perm", fmt="online", quality=6),
    _event(4, ["ai_ml"], [0.5, 0.5], days=-10),  # прошло
]


async def test_world_search_filters_like_sql() -> None:
    world = World(EVENTS, now=NOW)
    assert [e.id for e in await world.search(SearchQuery(topics=["golang"]), limit=5, now=NOW)] == [
        1,
        3,
    ]
    assert [e.id for e in await world.search(SearchQuery(city="perm"), limit=5, now=NOW)] == [3]
    assert await world.search(SearchQuery(topics=["ai_ml"]), limit=5, now=NOW) == []  # прошло


async def test_world_candidates_and_rocchio() -> None:
    world = World(EVENTS, now=NOW)
    cold = await world.generate(user_embedding=None, city=None, limit=5, now=NOW)
    assert [e.id for e in cold] == [2, 3, 1]  # по quality, без прошедших
    uow = world.uow()
    await uow.record_interaction(USER_ID, 1, "like")
    await uow.recompute_user_embedding(USER_ID)
    assert world.user.embedding == [1.0, 0.0]
    knn = await world.generate(
        user_embedding=world.user.embedding, city=None, limit=5, now=NOW, exclude_interacted_by=1
    )
    assert [e.id for e in knn] == [3, 2]  # 1 уже оценено


# ── симуляция на фейковых LLM ─────────────────────────────────────────────────
class AgentLLM:
    """Ход 1: предложить интерес golang; ход 2 — «да» обрабатывается без LLM;
    ход 3: подборка и ответ."""

    def __init__(self) -> None:
        self.steps = [
            ToolStep(
                text="",
                tool_calls=(
                    ToolCall(
                        id="a", name="update_profile", arguments={"add_interests": ["golang"]}
                    ),
                ),
                provider="fake",
                usage=LLMUsage(10, 5),
            ),
            ToolStep(
                text="",
                tool_calls=(ToolCall(id="b", name="recommend", arguments={"limit": 3}),),
                provider="fake",
            ),
            ToolStep(text="Вот что подходит", tool_calls=(), provider="fake"),
        ]

    async def complete_with_tools(self, *_: Any, **__: Any) -> ToolStep:
        return self.steps.pop(0)


class Gateway:
    """Симулятор пользователя + извлечение профиля анкеты."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    async def complete(self, messages: Sequence[LLMMessage], **_: Any) -> LLMResult:
        assert "<profile>" in messages[0].content  # скрытый профиль — только симулятору
        return LLMResult(text=self.lines.pop(0), provider="fake")

    async def structured_output(
        self, messages: Sequence[LLMMessage], schema: type, **_: Any
    ) -> Any:
        return ExtractedProfileSchema(interests=["golang"])


async def _encode(text: str) -> list[float]:
    return [1.0, 0.0] if "golang" in text or "Go" in text else [0.0, 1.0]


PERSONA = Persona(id="p01", about="Пишу на Go, фронтенд не интересен", city="perm",
                  preferred_format="online")


def _stack(agent_llm: Any, gateway: Gateway) -> Any:
    return build_stack(
        World(EVENTS, now=NOW),
        agent_llm=agent_llm,
        gateway=gateway,  # type: ignore[arg-type]
        embedding=QueryEmbedding(_encode, 2),
    )


async def test_simulated_dialog_builds_user_model_through_tools() -> None:
    gateway = Gateway(["Ищу что-нибудь по Go", "да", "покажи подборку"])
    stack = _stack(AgentLLM(), gateway)
    simulator = UserSimulator(gateway, PERSONA)  # type: ignore[arg-type]
    turns = await run_dialog(stack, simulator, turns=3)

    assert [t.stop_reason for t in turns] == ["confirmation", "resolved", "answer"]
    assert stack.world.user.profile.interests == ["golang"]  # записано только после «да»
    assert set(turns[2].shown[:2]) == {1, 3}  # Go-события ближе всех к профилю
    assert turns[0].ranking[0] == 2  # до подтверждения — холодный старт по quality
    assert turns[1].ranking[0] in (1, 3)
    assert "update_profile:pending" in turns[0].tools
    assert "update_profile:confirmed" in turns[1].tools


async def test_form_and_cold_baselines() -> None:
    gateway = Gateway([])
    cold = await run_cold(_stack(AgentLLM(), gateway))
    form_stack = _stack(AgentLLM(), gateway)
    form = await run_form(form_stack, PERSONA)
    assert cold[0] == 2
    assert form[0] in (1, 3) and form_stack.world.user.city == "perm"
    assert form_stack.world.user.profile.interests == ["golang"]


def test_summarize_and_pool() -> None:
    turns = [
        TurnLog(user="u", agent="a", shown=[2], ranking=[2, 1], stop_reason="answer"),
        TurnLog(user="u", agent="a", shown=[1], ranking=[1, 3], stop_reason="answer",
                tools=["recommend:ok"]),
    ]
    run = PersonaRun(persona_id="p01", cold=[2, 4], form=[1, 2], turns=turns)
    rels = {"p01": {1: 3, 3: 2, 2: 0}}
    assert turns_to_hit(turns, rels["p01"]) == 2
    report = summarize([run], rels)
    assert report.turns == 2 and len(report.ndcg_dialog_by_turn) == 2
    assert report.ndcg_dialog_by_turn[1] > report.ndcg_dialog_by_turn[0]
    assert report.hit_rate == 1.0 and report.mean_turns_to_hit == 2.0
    assert report.tool_usage == {"recommend:ok": 1}
    assert unjudged_pairs([run], rels) == {"p01": [4]}
