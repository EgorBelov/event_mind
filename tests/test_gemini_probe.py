"""Тесты автопробы Gemini-модели в _LLMChain."""
import pytest

from app.agents.recommendation import llm as llm_mod
from app.core.config import settings


@pytest.fixture(autouse=True)
def _reset_probe():
    """Каждый тест стартует с чистого probe-кэша + чистого breaker'а."""
    llm_mod.reset_gemini_probe_cache()
    llm_mod._provider_state.clear()
    llm_mod._breaker._consecutive_failures = 0
    llm_mod._breaker._opened_at = None
    yield
    llm_mod.reset_gemini_probe_cache()
    llm_mod._provider_state.clear()


def test_probe_returns_none_without_key(monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", "")
    assert llm_mod._probe_gemini_model() is None


def test_probe_picks_first_200(monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", "fake")
    monkeypatch.setattr(settings, "google_model", "")

    seen: list[str] = []

    class _Resp:
        def __init__(self, status_code):
            self.status_code = status_code

    def fake_post(url, params=None, json=None, timeout=None):
        # Парсим имя модели из URL: .../models/<name>:generateContent
        seg = url.split("/models/")[1].split(":")[0]
        seen.append(seg)
        # Первые две возвращают 429, третья — 200
        return _Resp(429 if len(seen) <= 2 else 200)

    monkeypatch.setattr("httpx.post", fake_post)
    picked = llm_mod._probe_gemini_model()
    # должна быть выбрана третья по порядку модель из fallback-списка
    assert picked == llm_mod._GEMINI_FALLBACK_MODELS[2]
    # пробежали ровно по первым 3 моделям (остановка на 200)
    assert seen[:3] == list(llm_mod._GEMINI_FALLBACK_MODELS[:3])


def test_probe_returns_none_when_all_fail(monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", "fake")
    monkeypatch.setattr(settings, "google_model", "")

    class _Resp:
        status_code = 429

    monkeypatch.setattr(
        "httpx.post", lambda *a, **kw: _Resp(),
    )
    assert llm_mod._probe_gemini_model() is None


def test_probe_explicit_model_tried_first(monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", "fake")
    monkeypatch.setattr(settings, "google_model", "gemini-pro-special")

    seen: list[str] = []

    class _Resp:
        status_code = 200

    def fake_post(url, params=None, json=None, timeout=None):
        seg = url.split("/models/")[1].split(":")[0]
        seen.append(seg)
        return _Resp()

    monkeypatch.setattr("httpx.post", fake_post)
    picked = llm_mod._probe_gemini_model()
    assert picked == "gemini-pro-special"
    assert seen == ["gemini-pro-special"]


def test_probe_cached_until_reset(monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", "fake")
    monkeypatch.setattr(settings, "google_model", "gemini-pro-special")

    calls = {"n": 0}

    class _Resp:
        status_code = 200

    def fake_post(*a, **kw):
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr("httpx.post", fake_post)
    assert llm_mod._resolve_gemini_model() == "gemini-pro-special"
    assert llm_mod._resolve_gemini_model() == "gemini-pro-special"
    assert calls["n"] == 1   # второй вызов идёт из кэша

    llm_mod.reset_gemini_probe_cache()
    assert llm_mod._resolve_gemini_model() == "gemini-pro-special"
    assert calls["n"] == 2


def test_chain_skips_gemini_link_when_no_model(monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", "fake")
    monkeypatch.setattr(settings, "groq_api_key", "fake")
    # форсируем «нет рабочей модели»
    monkeypatch.setattr(llm_mod, "_resolve_gemini_model", lambda: None)

    chain = llm_mod._build_chain()
    names = [link.name for link in chain if link.enabled]
    assert all(not n.startswith("gemini") for n in names)
    assert any(n.startswith("groq:") for n in names)
