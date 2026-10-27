"""Порт `LLMGateway` — единая точка доступа к LLM (цепочка провайдеров за адаптером).

Внутри инфраструктурной реализации: DeepSeek → Gemini → Groq70b → Groq8b, per-provider
cooldown, circuit-breaker, retry/timeout, учёт токенов, метрики. Прикладной код
и агент (`ToolCallingLLM`) ходят в LLM только через эти порты — никаких прямых
вызовов провайдеров.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel

Role = Literal["system", "user", "assistant", "tool"]

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Вызов инструмента, который запросила модель (tool calling)."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Role
    content: str
    # assistant: вызовы инструментов, запрошенные моделью на этом шаге
    tool_calls: tuple[ToolCall, ...] = ()
    # tool: ответ на вызов с этим id
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class LLMResult:
    text: str
    provider: str
    usage: LLMUsage = field(default_factory=LLMUsage)


@dataclass(frozen=True, slots=True)
class StructuredResult(Generic[T]):
    """Структура + какой провайдер её извлёк (провенанс: пишется рядом с данными)."""

    value: T
    provider: str


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Описание инструмента для модели: имя, назначение, JSON Schema аргументов."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolStep:
    """Ответ модели на шаге с инструментами: текст и/или запрошенные вызовы."""

    text: str
    tool_calls: tuple[ToolCall, ...]
    provider: str
    usage: LLMUsage = field(default_factory=LLMUsage)


class LLMUnavailable(RuntimeError):
    """Вся цепочка провайдеров недоступна или circuit-breaker открыт.

    Caller'ы обязаны ловить и деградировать (rule-based/пустой ответ) —
    сбой LLM не должен ронять запрос (требование отказоустойчивости).
    """


class LLMGateway(Protocol):
    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        """Свободная генерация. Идёт по цепочке до первого успеха."""
        ...

    async def structured_output(
        self,
        messages: Sequence[LLMMessage],
        schema: type[T],
        *,
        temperature: float | None = None,
    ) -> T:
        """Извлечь структуру в pydantic-схему (with_structured_output по цепочке)."""
        ...

    async def structured_output_result(
        self,
        messages: Sequence[LLMMessage],
        schema: type[T],
        *,
        temperature: float | None = None,
    ) -> StructuredResult[T]:
        """То же, что `structured_output`, плюс имя ответившего провайдера."""
        ...


class ToolCallingLLM(Protocol):
    """LLM с вызовом инструментов (для агента). Отдельный порт: остальным
    use-case'ам он не нужен, а фейкам в их тестах не нужно его реализовывать."""

    async def complete_with_tools(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolSpec],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ToolStep:
        """Один шаг: модель отвечает текстом или запрашивает вызовы инструментов."""
        ...
