"""Unit: диалоговый агент (A1–A3) — цикл хода, инструменты, ограничения,
подтверждение изменений, сессия (фейковая LLM, без БД/Redis)."""
from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from eventmind.application.agent.config import AgentConfig
from eventmind.application.agent.prompts import build_system_prompt
from eventmind.application.agent.session import (
    AgentSession,
    AgentSessionStore,
    PendingAction,
    dump_session,
    load_session,
    trim_history,
)
from eventmind.application.agent.tools import (
    AgentToolbox,
    GetEventTool,
    RecordFeedbackTool,
    SearchEventsTool,
    UpdateProfileTool,
    UpdateSettingsTool,
)
from eventmind.application.agent.use_cases import (
    AgentTurn,
    ConfirmAgentAction,
    GetAgentHistory,
    confirmation_intent,
)
from eventmind.application.ports.agent import AgentTurnRecord
from eventmind.application.ports.llm import (
    LLMMessage,
    LLMUnavailable,
    LLMUsage,
    ToolCall,
    ToolSpec,
    ToolStep,
)
from eventmind.application.ports.recommender import UserPrefs
from eventmind.application.search.schemas import SearchFilters
from eventmind.application.search.use_cases import SearchResult
from eventmind.domain.events.entities import Event
from eventmind.domain.recommender.user_model import ProfileChanges, UserProfile

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)  # вторник


def _event(event_id: int, title: str = "Go-митап") -> Event:
    return Event(
        id=event_id,
        source="habr",
        title=title,
        description="Доклады про Go и highload " * 5,
        format="online",
        city="perm",
        level="middle",
        date="2026-11-01",
        topics=["golang"],
    )


# ── фейки ─────────────────────────────────────────────────────────────────────
class ScriptedLLM:
    """Отдаёт заранее заданные шаги; запоминает, что видела модель."""

    def __init__(self, steps: Sequence[ToolStep | Exception]) -> None:
        self.steps = list(steps)
        self.calls: list[list[LLMMessage]] = []
        self.tools: list[list[ToolSpec]] = []

    async def complete_with_tools(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolSpec],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ToolStep:
        self.calls.append(list(messages))
        self.tools.append(list(tools))
        step = self.steps.pop(0) if self.steps else _answer("…")
        if isinstance(step, Exception):
            raise step
        return step


def _answer(text: str, tokens: int = 10) -> ToolStep:
    return ToolStep(text=text, tool_calls=(), provider="fake", usage=LLMUsage(tokens, 0))


def _call(name: str, tokens: int = 10, call_id: str = "c1", **args: Any) -> ToolStep:
    return ToolStep(
        text="",
        tool_calls=(ToolCall(id=call_id, name=name, arguments=args),),
        provider="fake",
        usage=LLMUsage(tokens, 0),
    )


class MemoryCache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


class ListJournal:
    def __init__(self) -> None:
        self.turns: list[AgentTurnRecord] = []

    async def record(self, turn: AgentTurnRecord) -> None:
        self.turns.append(turn)


class ContextUow:
    async def __aenter__(self) -> ContextUow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_profile(self, user_id: int) -> UserProfile | None:
        return UserProfile(user_id=user_id, interests=["golang"], goals=["перейти в ML"])

    async def get_user_prefs(self, user_id: int) -> UserPrefs:
        return UserPrefs(city="perm", preferred_format="online")

    async def known_topic_codes(self, *, limit: int) -> list[str]:
        return ["golang", "ai_ml", "devops"]


class FakeSearch:
    def __init__(self, results: list[Event]) -> None:
        self.results = results
        self.filters: list[SearchFilters] = []

    async def search_filters(self, filters: SearchFilters, *, limit: int = 5) -> SearchResult:
        self.filters.append(filters)
        return SearchResult(results=self.results[:limit], relaxed=False)


class FakeEvents:
    async def get_event(self, event_id: int) -> Event | None:
        return _event(event_id) if event_id < 100 else None

    async def get_events(self, event_ids: list[int]) -> list[Event]:
        return [_event(i) for i in event_ids]


class FakeRecord:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, str]] = []

    async def execute(self, user_id: int, event_id: int, action: str) -> None:
        self.calls.append((user_id, event_id, action))


class FakeApply:
    def __init__(self) -> None:
        self.calls: list[tuple[int, ProfileChanges]] = []

    async def execute(self, user_id: int, changes: ProfileChanges) -> UserProfile:
        self.calls.append((user_id, changes))
        return UserProfile(user_id=user_id, interests=list(changes.add_interests))


class FakeUpdateProfile:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, user_id: int, *, city: str | None, preferred_format: str | None) -> Any:
        self.calls.append({"city": city, "preferred_format": preferred_format})

        class _User:
            pass

        user = _User()
        user.city = city  # type: ignore[attr-defined]
        user.preferred_format = preferred_format  # type: ignore[attr-defined]
        return user


class _Clock:
    def now(self) -> datetime:
        return NOW


class Harness:
    def __init__(
        self,
        steps: Sequence[ToolStep | Exception],
        *,
        config: AgentConfig | None = None,
        results: list[Event] | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.llm = ScriptedLLM(steps)
        self.cache = MemoryCache()
        self.journal = ListJournal()
        self.search = FakeSearch(results if results is not None else [_event(1), _event(2)])
        self.record = FakeRecord()
        self.apply = FakeApply()
        self.update_settings = FakeUpdateProfile()
        self.toolbox = AgentToolbox(
            [
                SearchEventsTool(self.search),  # type: ignore[arg-type]
                GetEventTool(FakeEvents()),  # type: ignore[arg-type]
                RecordFeedbackTool(self.record),  # type: ignore[arg-type]
                UpdateProfileTool(self.apply),  # type: ignore[arg-type]
                UpdateSettingsTool(self.update_settings, self.cache),  # type: ignore[arg-type]
            ],
            allowed=self.config.allowed_tools,
        )
        ids = iter(f"id{i}" for i in range(100))
        self.sessions = AgentSessionStore(
            self.cache,
            ttl_seconds=60,
            history_limit=self.config.history_limit,
            id_factory=lambda: next(ids),
        )

    def _deps(self) -> tuple[Any, ...]:
        return (
            self.llm,
            self.toolbox,
            self.sessions,
            self.journal,
            ContextUow,
            self.cache,
            _Clock(),
            self.config,
        )

    @property
    def turn(self) -> AgentTurn:
        return AgentTurn(*self._deps())

    @property
    def confirm(self) -> ConfirmAgentAction:
        return ConfirmAgentAction(*self._deps())


# ── цикл хода ─────────────────────────────────────────────────────────────────
async def test_turn_searches_then_answers() -> None:
    h = Harness([_call("search_events", topics=["golang"], city="perm"), _answer("Нашёл два.")])
    reply = await h.turn.execute(7, "Go в Перми", channel="bot")

    assert reply.text == "Нашёл два."
    assert reply.stop_reason == "answer" and reply.steps == 2 and reply.tokens == 20
    assert [e.id for e in reply.events] == [1, 2]
    assert h.search.filters[0].topics == ["golang"] and h.search.filters[0].city == "perm"
    # результат инструмента вернулся модели сообщением role=tool с тем же id
    tool_msg = h.llm.calls[1][-1]
    assert tool_msg.role == "tool" and tool_msg.tool_call_id == "c1"
    assert json.loads(tool_msg.content)["count"] == 2
    # журнал: один ход, один успешный вызов
    (turn,) = h.journal.turns
    assert turn.channel == "bot" and turn.user_id == 7
    assert [(c.tool, c.status) for c in turn.tool_calls] == [("search_events", "ok")]
    session = await h.sessions.load(7)
    assert session.shown_event_ids == [1, 2]
    assert [m.role for m in session.messages] == ["user", "assistant", "tool", "assistant"]


async def test_system_prompt_carries_user_model_date_and_topics() -> None:
    h = Harness([_answer("Привет")])
    await h.turn.execute(1, "привет")
    system = h.llm.calls[0][0]
    assert system.role == "system"
    assert "2026-10-27, вторник" in system.content
    assert "2026-10-31" in system.content  # ближайшая суббота
    assert "интересы: golang" in system.content and "перейти в ML" in system.content
    assert "Темы каталога: golang, ai_ml, devops" in system.content


async def test_unknown_tool_is_rejected_and_model_recovers() -> None:
    h = Harness([_call("drop_database"), _answer("Не могу.")])
    reply = await h.turn.execute(1, "удали всё")
    assert reply.text == "Не могу."
    assert reply.tool_calls[0].status == "rejected"
    assert "недоступен" in h.llm.calls[1][-1].content


async def test_whitelist_hides_and_rejects_tools() -> None:
    config = AgentConfig(allowed_tools=frozenset({"search_events"}))
    h = Harness([_call("update_profile", add_interests=["ml"]), _answer("ok")], config=config)
    reply = await h.turn.execute(1, "мне интересен ML")
    assert [t.name for t in h.llm.tools[0]] == ["search_events"]
    assert reply.tool_calls[0].status == "rejected"
    assert reply.pending is None and h.apply.calls == []


async def test_invalid_arguments_go_back_to_model() -> None:
    h = Harness([_call("search_events", limit=500), _answer("Исправился")])
    reply = await h.turn.execute(1, "всё подряд")
    assert reply.tool_calls[0].status == "invalid"
    payload = json.loads(h.llm.calls[1][-1].content)
    assert payload["error"] == "invalid_arguments" and "limit" in payload["details"][0]


async def test_step_limit_stops_the_loop() -> None:
    config = AgentConfig(max_steps=3)
    h = Harness([_call("search_events", call_id=f"c{i}") for i in range(10)], config=config)
    reply = await h.turn.execute(1, "ищи")
    assert reply.stop_reason == "step_limit" and reply.steps == 3
    assert len(h.llm.calls) == 3
    assert reply.events  # найденное всё равно показываем


async def test_token_limit_stops_the_loop() -> None:
    config = AgentConfig(max_tokens_per_turn=100)
    h = Harness([_call("search_events", tokens=150), _answer("не дойдём")], config=config)
    reply = await h.turn.execute(1, "ищи")
    assert reply.stop_reason == "token_limit" and len(h.llm.calls) == 1


async def test_llm_unavailable_degrades_without_polluting_history() -> None:
    h = Harness([LLMUnavailable("down")])
    reply = await h.turn.execute(1, "Go в Перми")
    assert reply.degraded and reply.stop_reason == "llm_unavailable"
    assert (await h.sessions.load(1)).messages == []


async def test_empty_message_does_not_call_llm() -> None:
    h = Harness([])
    reply = await h.turn.execute(1, "   \x00 ")
    assert reply.stop_reason == "empty" and h.llm.calls == []


async def test_tool_crash_is_reported_to_model() -> None:
    class Boom:
        async def search_filters(self, *_: Any, **__: Any) -> SearchResult:
            raise RuntimeError("db down")

    h = Harness([_call("search_events"), _answer("Поиск недоступен")])
    h.toolbox = AgentToolbox([SearchEventsTool(Boom())])  # type: ignore[arg-type]
    reply = await h.turn.execute(1, "ищи")
    assert reply.tool_calls[0].status == "error"
    assert "временно недоступен" in h.llm.calls[1][-1].content


# ── правила инструментов ──────────────────────────────────────────────────────
async def test_feedback_only_for_events_shown_in_dialog() -> None:
    h = Harness(
        [
            _call("record_feedback", event_id=1, action="like"),
            _answer("Сначала покажу"),
            _call("search_events"),
            _answer("Вот"),
            _call("record_feedback", event_id=2, action="save"),
            _answer("Сохранил"),
        ]
    )
    first = await h.turn.execute(1, "лайкни первое")
    assert first.tool_calls[0].status == "error" and h.record.calls == []
    await h.turn.execute(1, "покажи Go")
    third = await h.turn.execute(1, "сохрани второе")
    assert third.tool_calls[0].status == "ok"
    assert h.record.calls == [(1, 2, "save")]


async def test_get_event_unknown_id_is_tool_error() -> None:
    h = Harness([_call("get_event", event_id=500), _answer("Нет такого")])
    reply = await h.turn.execute(1, "расскажи про 500")
    assert reply.tool_calls[0].status == "error"
    assert "не найдено" in h.llm.calls[1][-1].content


# ── подтверждение изменений модели пользователя ───────────────────────────────
async def test_profile_change_waits_for_confirmation() -> None:
    h = Harness([_call("update_profile", add_interests=["ai_ml"], add_anti_interests=["frontend"])])
    reply = await h.turn.execute(1, "хочу в ML, фронт не интересен")

    assert reply.stop_reason == "confirmation" and reply.pending is not None
    assert "AI / ML" in reply.text and "Frontend" in reply.text
    assert h.apply.calls == []  # без подтверждения ничего не меняется
    assert reply.tool_calls[0].status == "pending"

    done = await h.confirm.execute(1, reply.pending.id, approve=True)
    assert done.text.startswith("✅")
    assert h.apply.calls[0][1].add_interests == ("ai_ml",)
    assert done.tool_calls[0].status == "confirmed"
    session = await h.sessions.load(1)
    assert session.pending is None
    assert [m.role for m in session.messages] == ["user", "assistant", "tool", "assistant"]


async def test_declined_change_is_not_applied() -> None:
    h = Harness([_call("update_settings", city="Пермь")])
    reply = await h.turn.execute(1, "я теперь в Перми")
    assert reply.pending is not None and "Пермь" in reply.text
    done = await h.confirm.execute(1, reply.pending.id, approve=False)
    assert done.tool_calls[0].status == "declined"
    assert h.update_settings.calls == []


async def test_text_yes_confirms_pending_change() -> None:
    h = Harness([_call("update_settings", format="any")])
    await h.turn.execute(1, "формат не важен")
    reply = await h.turn.execute(1, "Да!")
    assert reply.stop_reason == "resolved"
    assert h.update_settings.calls == [{"city": None, "preferred_format": ""}]
    assert len(h.llm.calls) == 1  # подтверждение без вызова LLM


async def test_new_request_drops_pending_change() -> None:
    h = Harness([_call("update_profile", add_goals=["стать тимлидом"]), _answer("Ищу")])
    first = await h.turn.execute(1, "хочу стать тимлидом")
    assert first.pending is not None
    await h.turn.execute(1, "а что есть по DevOps?")
    assert h.apply.calls == []
    session = await h.sessions.load(1)
    assert session.pending is None
    stale = await h.confirm.execute(1, first.pending.id, approve=True)
    assert "неактуально" in stale.text and h.apply.calls == []


async def test_only_one_change_per_turn() -> None:
    two = ToolStep(
        text="",
        tool_calls=(
            ToolCall(id="a", name="update_profile", arguments={"add_interests": ["ml"]}),
            ToolCall(id="b", name="update_settings", arguments={"city": "spb"}),
        ),
        provider="fake",
    )
    h = Harness([two])
    reply = await h.turn.execute(1, "ML и Питер")
    assert [c.status for c in reply.tool_calls] == ["pending", "rejected"]
    assert reply.pending is not None and reply.pending.tool == "update_profile"


async def test_history_exposes_only_visible_messages() -> None:
    h = Harness([_call("search_events"), _answer("Вот два события")])
    await h.turn.execute(1, "Go")
    items, pending = await GetAgentHistory(h.sessions).execute(1)
    assert [(i.role, i.text) for i in items] == [("user", "Go"), ("assistant", "Вот два события")]
    assert pending is None


# ── сессия, промпт, схемы ─────────────────────────────────────────────────────
def test_trim_history_starts_with_user_message() -> None:
    msgs = [
        LLMMessage(role="user", content="1"),
        LLMMessage(role="assistant", content="", tool_calls=(ToolCall(id="x", name="t"),)),
        LLMMessage(role="tool", content="{}", tool_call_id="x"),
        LLMMessage(role="assistant", content="2"),
        LLMMessage(role="user", content="3"),
        LLMMessage(role="assistant", content="4"),
    ]
    trimmed = trim_history(msgs, 4)
    assert [m.content for m in trimmed] == ["3", "4"]
    assert trim_history(msgs, 10) == msgs


def test_session_roundtrip() -> None:
    session = AgentSession(
        session_id="s",
        messages=[
            LLMMessage(role="user", content="привет"),
            LLMMessage(
                role="assistant",
                content="",
                tool_calls=(ToolCall(id="c", name="search_events", arguments={"city": "perm"}),),
            ),
            LLMMessage(role="tool", content="{}", tool_call_id="c"),
        ],
        shown_event_ids=[3, 4],
        pending=PendingAction(id="p", tool="update_settings", arguments={"city": "perm"},
                              description="d"),
    )
    assert load_session(dump_session(session)) == session


async def test_corrupted_session_starts_fresh() -> None:
    cache = MemoryCache()
    cache.data["agent:v1:1"] = "{not json"
    store = AgentSessionStore(cache, ttl_seconds=1, history_limit=5, id_factory=lambda: "new")
    session = await store.load(1)
    assert session.session_id == "new" and session.messages == []


def test_remember_shown_keeps_recent_order() -> None:
    session = AgentSession(session_id="s", shown_event_ids=[1, 2, 3])
    session.remember_shown([2, 4])
    assert session.shown_event_ids == [1, 3, 2, 4]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("да", True), ("Да!", True), ("ок", True), ("нет", False), ("Отмена.", False),
     ("да, но только онлайн", None), ("что по Go?", None)],
)
def test_confirmation_intent(text: str, expected: bool | None) -> None:
    assert confirmation_intent(text) is expected


def test_tool_schemas_are_provider_friendly() -> None:
    h = Harness([])
    for spec in h.toolbox.specs():
        dumped = json.dumps(spec.parameters)
        assert '"title"' not in dumped and '"type": "null"' not in dumped
        assert spec.parameters["type"] == "object"
    search = next(s for s in h.toolbox.specs() if s.name == "search_events")
    assert search.parameters["properties"]["format"]["enum"] == ["online", "offline", "hybrid"]


def test_system_prompt_without_profile() -> None:
    prompt = build_system_prompt(NOW, profile={}, topics=[])
    assert "пока пустая" in prompt and "Темы каталога" not in prompt
