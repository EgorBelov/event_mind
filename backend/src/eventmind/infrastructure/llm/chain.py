"""`LLMChain` — реализация порта `LLMGateway`: цепочка провайдеров с fallback.

invoke идёт по включённым звеньям до первого успеха; звенья на cooldown
пропускаются; открытый circuit-breaker отсекает всё сразу. Совместимо и с
langchain-моделями (Gemini/Groq), и с фейками в тестах — звено типизировано
структурным протоколом `ChatModel`.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from eventmind.application.ports.llm import (
    LLMMessage,
    LLMResult,
    LLMUnavailable,
    LLMUsage,
)
from eventmind.infrastructure.llm.breaker import CircuitBreaker, ProviderCooldown
from eventmind.infrastructure.telemetry.metrics import (
    LLM_REQUEST_DURATION_SECONDS,
    LLM_REQUESTS_TOTAL,
    LLM_TOKENS_TOTAL,
)

_logger = structlog.get_logger("eventmind.llm")

T = TypeVar("T", bound=BaseModel)


class SupportsAInvoke(Protocol):
    async def ainvoke(self, input: Any, **kwargs: Any) -> Any: ...


class ChatModel(Protocol):
    """Структурный контракт звена: langchain-модель или фейк в тестах."""

    async def ainvoke(self, input: Any, **kwargs: Any) -> Any: ...
    def with_structured_output(self, schema: Any, **kwargs: Any) -> SupportsAInvoke: ...
    def bind_tools(self, tools: Any, **kwargs: Any) -> Any: ...


@dataclass
class ProviderLink:
    name: str
    factory: Callable[[], ChatModel]
    enabled: bool = True
    _model: ChatModel | None = None

    def model(self) -> ChatModel:
        if self._model is None:
            self._model = self.factory()
        return self._model


def _to_lc(messages: Sequence[LLMMessage]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for m in messages:
        if m.role == "system":
            out.append(SystemMessage(content=m.content))
        elif m.role == "assistant":
            out.append(AIMessage(content=m.content))
        else:
            out.append(HumanMessage(content=m.content))
    return out


def _extract_usage(message: Any) -> LLMUsage:
    usage = getattr(message, "usage_metadata", None)
    if isinstance(usage, dict):
        return LLMUsage(
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )
    return LLMUsage()


def _content_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    return str(content)


class LLMChain:
    """Цепочка LLM-провайдеров за портом `LLMGateway`."""

    def __init__(
        self,
        links: list[ProviderLink],
        *,
        breaker: CircuitBreaker,
        cooldown: ProviderCooldown,
        timeout_seconds: float = 45.0,
        default_temperature: float = 0.3,
    ) -> None:
        self._links = links
        self._breaker = breaker
        self._cooldown = cooldown
        self._timeout = timeout_seconds
        self._default_temperature = default_temperature

    # ── публичный контракт LLMGateway ────────────────────────────────────
    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        lc = _to_lc(messages)
        provider, message = await self._run(lambda model: model.ainvoke(lc))
        usage = _extract_usage(message)
        if usage.input_tokens:
            LLM_TOKENS_TOTAL.labels(provider, "input").inc(usage.input_tokens)
        if usage.output_tokens:
            LLM_TOKENS_TOTAL.labels(provider, "output").inc(usage.output_tokens)
        return LLMResult(text=_content_text(message), provider=provider, usage=usage)

    async def structured_output(
        self,
        messages: Sequence[LLMMessage],
        schema: type[T],
        *,
        temperature: float | None = None,
    ) -> T:
        lc = _to_lc(messages)

        async def call(model: ChatModel) -> Any:
            return await model.with_structured_output(schema).ainvoke(lc)

        _provider, result = await self._run(call)
        return result  # type: ignore[no-any-return]

    def bind_tools(self, tools: Sequence[object]) -> Any:
        """Привязать tools к первому включённому звену (seam для LangGraph, M3+)."""
        for link in self._links:
            if link.enabled:
                return link.model().bind_tools(list(tools))
        raise LLMUnavailable("Нет включённых LLM-провайдеров для bind_tools")

    # ── ядро fallback + breaker + cooldown ───────────────────────────────
    async def _run(
        self, call: Callable[[ChatModel], Awaitable[Any]]
    ) -> tuple[str, Any]:
        if self._breaker.is_open():
            LLM_REQUESTS_TOTAL.labels("chain", "breaker_open").inc()
            raise LLMUnavailable("LLM circuit breaker открыт — fast fail")

        enabled = [link for link in self._links if link.enabled]
        if not enabled:
            raise LLMUnavailable(
                "Нет настроенных LLM-провайдеров (задай GOOGLE_API_KEY или GROQ_API_KEY)"
            )

        last_exc: Exception | None = None
        for link in enabled:
            if self._cooldown.should_skip(link.name):
                LLM_REQUESTS_TOTAL.labels(link.name, "skipped").inc()
                continue
            started = time.perf_counter()
            try:
                model = link.model()
                result = await asyncio.wait_for(call(model), timeout=self._timeout)
            except Exception as exc:  # любой сбой звена — пробуем следующее
                last_exc = exc
                self._cooldown.record_failure(link.name)
                LLM_REQUESTS_TOTAL.labels(link.name, "error").inc()
                _logger.warning("llm_provider_failed", provider=link.name, error=str(exc))
                continue
            LLM_REQUEST_DURATION_SECONDS.labels(link.name).observe(
                time.perf_counter() - started
            )
            self._cooldown.record_success(link.name)
            self._breaker.record_success()
            LLM_REQUESTS_TOTAL.labels(link.name, "success").inc()
            return link.name, result

        # Вся цепочка упала — сигнал breaker'у.
        self._breaker.record_failure()
        raise LLMUnavailable("Все LLM-провайдеры недоступны") from last_exc

    # ── интроспекция/управление (admin) ──────────────────────────────────
    def status(self) -> dict[str, Any]:
        return {
            "breaker_open": self._breaker.is_open(),
            "providers": [
                {"name": link.name, "enabled": link.enabled} for link in self._links
            ],
        }

    def set_links(self, links: list[ProviderLink]) -> None:
        """Заменить звенья (после reprobe Gemini-модели)."""
        self._links = links
