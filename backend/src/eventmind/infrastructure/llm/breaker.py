"""Circuit-breaker цепочки + per-provider cooldown.

Портировано из v1 (`_CircuitBreaker`, `_provider_*`), но без module-глобалов:
состояние живёт в экземплярах (по одному на LLMChain). Часы инъектируются
(`clock`) для детерминизма в тестах.
"""
from __future__ import annotations

import time
from collections.abc import Callable

import structlog

_logger = structlog.get_logger("eventmind.llm")

Clock = Callable[[], float]


class CircuitBreaker:
    """Если ВСЯ цепочка падает `threshold` раз подряд — открываемся на `cooldown`.

    Пока открыт, вызовы отсекаются быстро (без ожидания таймаутов провайдеров).
    После cooldown — half-open: следующий вызов пробуется.
    """

    def __init__(
        self,
        *,
        threshold: int = 5,
        cooldown_seconds: float = 120.0,
        clock: Clock = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        return self._clock() - self._opened_at < self._cooldown

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._threshold and self._opened_at is None:
            self._opened_at = self._clock()
            _logger.warning(
                "llm_breaker_open",
                failures=self._consecutive_failures,
                cooldown_s=self._cooldown,
            )


class ProviderCooldown:
    """Per-провайдер skip: `threshold` подряд фейлов одного звена → пауза `cooldown`.

    Не тратим ~2 c на звено, которое стабильно 429-ит (дневная квота Groq и т.п.).
    """

    def __init__(
        self,
        *,
        threshold: int = 2,
        cooldown_seconds: float = 600.0,
        clock: Clock = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._state: dict[str, tuple[int, float | None]] = {}

    def should_skip(self, name: str) -> bool:
        failures, opened_at = self._state.get(name, (0, None))
        if opened_at is None:
            return False
        if self._clock() - opened_at >= self._cooldown:
            self._state[name] = (0, None)  # cooldown истёк — даём шанс
            return False
        return True

    def record_success(self, name: str) -> None:
        self._state[name] = (0, None)

    def record_failure(self, name: str) -> None:
        failures, opened_at = self._state.get(name, (0, None))
        failures += 1
        if failures >= self._threshold and opened_at is None:
            opened_at = self._clock()
            _logger.info("llm_provider_cooldown", provider=name, cooldown_s=self._cooldown)
        self._state[name] = (failures, opened_at)
