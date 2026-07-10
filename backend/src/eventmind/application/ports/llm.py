"""Порт `LLMGateway` — единая точка доступа к LLM (цепочка провайдеров за адаптером).

Внутри инфраструктурной реализации: Gemini → Groq70b → Groq8b, per-provider
cooldown, circuit-breaker, retry/timeout, учёт токенов, метрики. Прикладной код
и LangGraph-графы (M3+) ходят в LLM только через этот порт — никаких прямых
вызовов провайдеров.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel

Role = Literal["system", "user", "assistant"]

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Role
    content: str


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
