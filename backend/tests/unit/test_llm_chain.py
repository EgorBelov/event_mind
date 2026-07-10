"""Unit: LLMChain — fallback, structured_output, breaker, cooldown (фейковые провайдеры)."""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from eventmind.application.ports.llm import LLMMessage, LLMUnavailable
from eventmind.infrastructure.llm.breaker import CircuitBreaker, ProviderCooldown
from eventmind.infrastructure.llm.chain import LLMChain, ProviderLink


class _FakeAI:
    def __init__(self, content: str, usage: dict[str, int] | None = None) -> None:
        self.content = content
        self.usage_metadata = usage


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
    ) -> None:
        self.content = content
        self.usage = usage
        self.fail = fail
        self.structured_result = structured_result
        self.calls = 0

    async def ainvoke(self, _input: Any, **_kw: Any) -> Any:
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider boom")
        return _FakeAI(self.content, self.usage)

    def with_structured_output(self, _schema: Any, **_kw: Any) -> _FakeStructured:
        return _FakeStructured(self.structured_result, self.fail)

    def bind_tools(self, _tools: Any, **_kw: Any) -> FakeChatModel:
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
