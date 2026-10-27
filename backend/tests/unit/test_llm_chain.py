"""Unit: LLMChain — fallback, structured_output, breaker, cooldown (фейковые провайдеры)."""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from eventmind.application.ports.llm import (
    LLMMessage,
    LLMUnavailable,
    ToolCall,
    ToolSpec,
)
from eventmind.infrastructure.llm.breaker import CircuitBreaker, ProviderCooldown
from eventmind.infrastructure.llm.chain import LLMChain, ProviderLink


class _FakeAI:
    def __init__(
        self,
        content: Any,
        usage: dict[str, int] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        self.content = content
        self.usage_metadata = usage
        self.tool_calls = tool_calls or []


class _FakeStructured:
    def __init__(self, result: Any, fail: bool) -> None:
        self._result = result
        self._fail = fail

    async def ainvoke(self, _input: Any, **_kw: Any) -> Any:
        if self._fail:
            raise RuntimeError("structured boom")
        return self._result


class FakeChatModel:
    def __init__(
        self,
        *,
        content: str = "ok",
        usage: dict[str, int] | None = None,
        fail: bool = False,
        structured_result: Any = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        self.content = content
        self.usage = usage
        self.fail = fail
        self.structured_result = structured_result
        self.tool_calls = tool_calls
        self.calls = 0
        self.inputs: list[Any] = []
        self.bound_tools: list[Any] = []

    async def ainvoke(self, _input: Any, **_kw: Any) -> Any:
        self.calls += 1
        self.inputs.append(_input)
        if self.fail:
            raise RuntimeError("provider boom")
        return _FakeAI(self.content, self.usage, self.tool_calls)

    def with_structured_output(self, _schema: Any, **_kw: Any) -> _FakeStructured:
        return _FakeStructured(self.structured_result, self.fail)

    def bind_tools(self, tools: Any, **_kw: Any) -> FakeChatModel:
        self.bound_tools = list(tools)
        return self


def _chain(*models: FakeChatModel, breaker: CircuitBreaker | None = None) -> LLMChain:
    links = [
        ProviderLink(name=f"p{i}", factory=lambda m=m: m, enabled=True)
        for i, m in enumerate(models)
    ]
    return LLMChain(
        links,
        breaker=breaker or CircuitBreaker(threshold=5, cooldown_seconds=100),
        cooldown=ProviderCooldown(threshold=2, cooldown_seconds=600),
    )


MSGS = [LLMMessage(role="user", content="hi")]


async def test_complete_uses_first_provider() -> None:
    a = FakeChatModel(content="from-a", usage={"input_tokens": 3, "output_tokens": 5})
    b = FakeChatModel(content="from-b")
    result = await _chain(a, b).complete(MSGS)
    assert result.text == "from-a"
    assert result.provider == "p0"
    assert result.usage.total_tokens == 8
    assert b.calls == 0  # второй провайдер не тронут


async def test_complete_falls_back_when_first_fails() -> None:
    a = FakeChatModel(fail=True)
    b = FakeChatModel(content="from-b")
    result = await _chain(a, b).complete(MSGS)
    assert result.text == "from-b"
    assert result.provider == "p1"


async def test_complete_raises_when_all_fail() -> None:
    chain = _chain(FakeChatModel(fail=True), FakeChatModel(fail=True))
    with pytest.raises(LLMUnavailable):
        await chain.complete(MSGS)


async def test_breaker_opens_after_chain_failures_and_fast_fails() -> None:
    breaker = CircuitBreaker(threshold=1, cooldown_seconds=100)
    a = FakeChatModel(fail=True)
    chain = _chain(a, breaker=breaker)
    with pytest.raises(LLMUnavailable):
        await chain.complete(MSGS)
    calls_before = a.calls
    # breaker открыт → следующий вызов не трогает провайдера
    with pytest.raises(LLMUnavailable):
        await chain.complete(MSGS)
    assert a.calls == calls_before


class _Schema(BaseModel):
    city: str


async def test_structured_output_returns_parsed_and_falls_back() -> None:
    a = FakeChatModel(fail=True)
    b = FakeChatModel(structured_result=_Schema(city="moscow"))
    result = await _chain(a, b).structured_output(MSGS, _Schema)
    assert isinstance(result, _Schema)
    assert result.city == "moscow"


async def test_no_enabled_providers_raises() -> None:
    link = ProviderLink(name="p", factory=lambda: FakeChatModel(), enabled=False)
    chain = LLMChain(
        [link],
        breaker=CircuitBreaker(),
        cooldown=ProviderCooldown(),
    )
    with pytest.raises(LLMUnavailable):
        await chain.complete(MSGS)


async def test_provider_cooldown_skips_repeatedly_failing_provider() -> None:
    a = FakeChatModel(fail=True)
    b = FakeChatModel(content="from-b")
    chain = _chain(a, b)
    # два фейла подряд на p0 → он уходит в cooldown
    await chain.complete(MSGS)
    await chain.complete(MSGS)
    calls_after_two = a.calls
    await chain.complete(MSGS)
    assert a.calls == calls_after_two  # p0 пропущен, ответил p1


# ── tool calling (агент) ─────────────────────────────────────────────────────
SPEC = ToolSpec(
    name="search_events",
    description="Поиск",
    parameters={"type": "object", "properties": {"city": {"type": "string"}}},
)


async def test_complete_with_tools_parses_calls_and_binds_openai_schema() -> None:
    model = FakeChatModel(
        content="",
        usage={"input_tokens": 7, "output_tokens": 3},
        tool_calls=[
            {"id": "call_1", "name": "search_events", "args": {"city": "perm"}},
            {"name": "", "args": {}},  # мусор без имени отбрасывается
        ],
    )
    step = await _chain(model).complete_with_tools(MSGS, [SPEC])
    assert step.tool_calls == (
        ToolCall(id="call_1", name="search_events", arguments={"city": "perm"}),
    )
    assert step.provider == "p0" and step.usage.total_tokens == 10
    assert model.bound_tools == [
        {
            "type": "function",
            "function": {"name": "search_events", "description": "Поиск",
                         "parameters": SPEC.parameters},
        }
    ]


async def test_complete_with_tools_falls_back_to_next_provider() -> None:
    a = FakeChatModel(fail=True)
    b = FakeChatModel(content="ответ")
    step = await _chain(a, b).complete_with_tools(MSGS, [SPEC])
    assert step.text == "ответ" and step.tool_calls == () and step.provider == "p1"


async def test_tool_history_is_converted_to_langchain_messages() -> None:
    from langchain_core.messages import AIMessage, ToolMessage

    model = FakeChatModel(content="ok")
    history = [
        LLMMessage(role="user", content="Go в Перми"),
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=(ToolCall(id="c1", name="search_events", arguments={"city": "perm"}),),
        ),
        LLMMessage(role="tool", content='{"count": 0}', tool_call_id="c1"),
    ]
    await _chain(model).complete_with_tools(history, [SPEC])
    _, ai, tool = model.inputs[0]
    assert isinstance(ai, AIMessage) and ai.tool_calls[0]["id"] == "c1"
    assert ai.tool_calls[0]["args"] == {"city": "perm"}
    assert isinstance(tool, ToolMessage) and tool.tool_call_id == "c1"


async def test_list_content_from_gemini_is_joined() -> None:
    parts = [{"type": "text", "text": "При"}, {"type": "text", "text": "вет"}]
    model = FakeChatModel(content=parts)
    step = await _chain(model).complete_with_tools(MSGS, [SPEC])
    assert step.text == "Привет"


# ── параметры вызова (температура, лимит ответа) ─────────────────────────────
class _TunableModel(FakeChatModel):
    """Как langchain-модель: pydantic-копия с обновлёнными полями."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.updates: list[dict[str, Any]] = []
        self.applied: dict[str, Any] = {}

    def model_copy(self, *, update: dict[str, Any]) -> _TunableModel:
        self.updates.append(update)
        copy = _TunableModel(content=self.content, structured_result=self.structured_result)
        copy.applied = update
        copy.updates = self.updates
        return copy


async def test_call_temperature_and_max_tokens_reach_the_model() -> None:
    model = _TunableModel(content="ok")
    await _chain(model).complete(MSGS, temperature=0.0, max_tokens=50)
    assert model.updates == [{"temperature": 0.0, "max_tokens": 50}]


async def test_gemini_uses_its_own_max_tokens_field() -> None:
    model = _TunableModel(content="ok")
    link = ProviderLink(name="gemini", factory=lambda: model, max_tokens_field="max_output_tokens")
    chain = LLMChain([link], breaker=CircuitBreaker(), cooldown=ProviderCooldown())
    await chain.complete(MSGS, max_tokens=10)
    assert model.updates == [{"max_output_tokens": 10}]


async def test_no_call_params_keeps_model_and_structured_reports_provider() -> None:
    model = _TunableModel(structured_result=_Schema(city="perm"))
    result = await _chain(FakeChatModel(fail=True), model).structured_output_result(
        MSGS, _Schema, temperature=0.0
    )
    assert result.value == _Schema(city="perm") and result.provider == "p1"
    assert model.updates == [{"temperature": 0.0}]
    await _chain(model).complete(MSGS)
    assert model.updates == [{"temperature": 0.0}]  # без параметров копия не делается
