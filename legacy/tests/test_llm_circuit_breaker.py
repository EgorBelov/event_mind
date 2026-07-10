"""Тесты circuit-breaker'а + multi-provider цепочки."""
import pytest

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

    with pytest.raises(llm_mod.CircuitOpenError):
        llm_mod.llm.invoke("anything")

    # cleanup чтобы не «протёк» в другие тесты
    _reset(llm_mod._breaker)
    llm_mod._breaker.failure_threshold = 5


# ─── Multi-provider chain ────────────────────────────────────────────────


class _FakeModel:
    """Минимальный мок ChatModel для тестов цепочки."""

    def __init__(self, *, raises=None, returns=None):
        self.raises = raises
        self.returns = returns
        self.calls = 0

    def invoke(self, *a, **kw):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.returns


def _chain_with(*pairs):
    """Помощник: вернуть готовую цепочку из пар (name, FakeModel)."""
    links = []
    for name, model in pairs:
        link = llm_mod._ProviderLink(name, build=lambda m=model: m, enabled=True)
        # подмена кэша, чтобы build() не вызывался
        link._cached = model
        links.append(link)
    return links


@pytest.fixture(autouse=True)
def reset_provider_state():
    """Перед каждым тестом сбрасываем breaker и per-provider state."""
    _reset(llm_mod._breaker)
    llm_mod._provider_state.clear()
    yield
    _reset(llm_mod._breaker)
    llm_mod._provider_state.clear()


def test_chain_uses_first_provider_on_success(monkeypatch):
    primary = _FakeModel(returns="from-gemini")
    fallback = _FakeModel(returns="from-groq")
    chain = _chain_with(("gemini", primary), ("groq:70b", fallback))

    obj = llm_mod._LLMChain()
    obj._chain = chain
    assert obj.invoke("hi") == "from-gemini"
    assert primary.calls == 1
    assert fallback.calls == 0


def test_chain_falls_through_to_next_on_error(monkeypatch):
    primary = _FakeModel(raises=RuntimeError("429 TPD"))
    fallback = _FakeModel(returns="from-groq")
    chain = _chain_with(("gemini", primary), ("groq:70b", fallback))

    obj = llm_mod._LLMChain()
    obj._chain = chain
    assert obj.invoke("hi") == "from-groq"
    assert primary.calls == 1
    assert fallback.calls == 1


def test_chain_skips_provider_in_cooldown():
    primary = _FakeModel(raises=RuntimeError("fail-1"))
    fallback = _FakeModel(returns="from-groq")
    chain = _chain_with(("gemini", primary), ("groq:70b", fallback))

    obj = llm_mod._LLMChain()
    obj._chain = chain

    # Прогоняем provider 2 раза, чтобы у него опен cooldown
    for _ in range(llm_mod._PROVIDER_FAIL_THRESHOLD):
        obj.invoke("x")
    primary_calls_after_open = primary.calls

    # Следующий invoke — primary должен быть skipped, fallback продолжает.
    obj.invoke("y")
    assert primary.calls == primary_calls_after_open   # primary не звался
    assert fallback.calls == primary_calls_after_open + 1


def test_chain_all_failed_records_breaker_failure():
    primary = _FakeModel(raises=RuntimeError("a"))
    fallback = _FakeModel(raises=RuntimeError("b"))
    chain = _chain_with(("gemini", primary), ("groq:70b", fallback))

    obj = llm_mod._LLMChain()
    obj._chain = chain
    with pytest.raises(RuntimeError):
        obj.invoke("x")
    # breaker зафиксировал 1 fail на всю цепочку (не 2)
    assert llm_mod._breaker._consecutive_failures == 1


def test_chain_raises_if_no_providers_configured(monkeypatch):
    obj = llm_mod._LLMChain()
    obj._chain = []
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY|GROQ_API_KEY"):
        obj.invoke("x")
