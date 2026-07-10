"""Unit: circuit-breaker и per-provider cooldown (инъекция часов → детерминизм)."""
from __future__ import annotations

from eventmind.infrastructure.llm.breaker import CircuitBreaker, ProviderCooldown


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_breaker_opens_after_threshold() -> None:
    clock = _Clock()
    b = CircuitBreaker(threshold=3, cooldown_seconds=100, clock=clock)
    assert not b.is_open()
    b.record_failure()
    b.record_failure()
    assert not b.is_open()  # ещё не достигли порога
    b.record_failure()
    assert b.is_open()  # 3 подряд → открыт


def test_breaker_half_open_after_cooldown() -> None:
    clock = _Clock()
    b = CircuitBreaker(threshold=1, cooldown_seconds=100, clock=clock)
    b.record_failure()
    assert b.is_open()
    clock.t = 100.0  # cooldown истёк
    assert not b.is_open()


def test_breaker_success_resets() -> None:
    clock = _Clock()
    b = CircuitBreaker(threshold=2, cooldown_seconds=100, clock=clock)
    b.record_failure()
    b.record_success()
    b.record_failure()
    assert not b.is_open()  # счётчик сброшен успехом


def test_provider_cooldown_skips_after_threshold_and_resets() -> None:
    clock = _Clock()
    c = ProviderCooldown(threshold=2, cooldown_seconds=600, clock=clock)
    assert not c.should_skip("groq")
    c.record_failure("groq")
    assert not c.should_skip("groq")  # 1 фейл — ещё пробуем
    c.record_failure("groq")
    assert c.should_skip("groq")  # 2 подряд — пропускаем
    clock.t = 600.0
    assert not c.should_skip("groq")  # cooldown истёк — снова доступен


def test_provider_cooldown_success_clears() -> None:
    c = ProviderCooldown(threshold=1, cooldown_seconds=600)
    c.record_failure("gemini")
    assert c.should_skip("gemini")
    c.record_success("gemini")
    assert not c.should_skip("gemini")
