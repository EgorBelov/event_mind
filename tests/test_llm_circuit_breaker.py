"""Тесты circuit-breaker'а вокруг Groq."""
from app.agents.recommendation import llm as llm_mod


def _reset(breaker):
    breaker._consecutive_failures = 0
    breaker._opened_at = None


def test_breaker_opens_after_threshold():
    b = llm_mod._CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)
    assert not b.is_open()
    b.record_failure()
    b.record_failure()
    assert not b.is_open()
    b.record_failure()
    assert b.is_open()


def test_breaker_closes_on_success():
    b = llm_mod._CircuitBreaker(failure_threshold=2, cooldown_seconds=60.0)
    b.record_failure()
    b.record_failure()
    assert b.is_open()
    b.record_success()
    assert not b.is_open()


def test_breaker_half_open_after_cooldown(monkeypatch):
    b = llm_mod._CircuitBreaker(failure_threshold=1, cooldown_seconds=1.0)
    b.record_failure()
    assert b.is_open()
    # Симулируем «прошло больше cooldown»
    b._opened_at -= 10.0
    assert not b.is_open()


def test_invoke_fast_fail_when_open(monkeypatch):
    _reset(llm_mod._breaker)
    # форсируем circuit OPEN
    llm_mod._breaker.failure_threshold = 1
    llm_mod._breaker.record_failure()
    assert llm_mod._breaker.is_open()

    import pytest

    with pytest.raises(llm_mod.CircuitOpenError):
        llm_mod.llm.invoke("anything")

    # cleanup чтобы не «протёк» в другие тесты
    _reset(llm_mod._breaker)
    llm_mod._breaker.failure_threshold = 5
