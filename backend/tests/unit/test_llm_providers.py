"""Unit: сборка звеньев LLM-цепочки — порядок DeepSeek → Gemini → Groq, DEEPSEEK_MODELS."""
from __future__ import annotations

from typing import Any

from eventmind.config import Settings
from eventmind.infrastructure.llm.providers import build_links


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "deepseek_api_key": "ds-key",
        "deepseek_models": "",
        "google_api_key": "g-key",
        "groq_api_key": "groq-key",
        "groq_model": "llama-3.3-70b-versatile",
        "groq_fallback_model": "llama-3.1-8b-instant",
    }
    base.update(overrides)
    return Settings(**base)


def test_deepseek_model_list_parses_comma_separated_in_order() -> None:
    s = _settings(deepseek_models=" deepseek-v4-pro, deepseek-flash ,,")
    assert s.deepseek_model_list == ["deepseek-v4-pro", "deepseek-flash"]


def test_deepseek_model_list_defaults_when_empty() -> None:
    assert _settings(deepseek_models="").deepseek_model_list == ["deepseek-flash"]


def test_chain_starts_with_deepseek_models_then_gemini_then_groq() -> None:
    links = build_links(
        _settings(deepseek_models="deepseek-v4-pro,deepseek-flash"),
        gemini_model="gemini-2.0-flash",
    )
    assert [link.name for link in links] == [
        "deepseek:deepseek-v4-pro",
        "deepseek:deepseek-flash",
        "gemini:gemini-2.0-flash",
        "groq:llama-3.3-70b-versatile",
        "groq:llama-3.1-8b-instant",
    ]
    assert all(link.enabled for link in links)


def test_deepseek_links_disabled_without_key() -> None:
    links = build_links(_settings(deepseek_api_key=""), gemini_model="gemini-2.0-flash")
    deepseek = [link for link in links if link.name.startswith("deepseek:")]
    assert deepseek
    assert not any(link.enabled for link in deepseek)
    assert links[len(deepseek)].enabled  # первым реально отвечает Gemini


def test_deepseek_link_builds_chat_model_lazily() -> None:
    links = build_links(_settings(deepseek_models="deepseek-flash"), gemini_model=None)
    model = links[0].model()
    assert type(model).__name__ == "ChatDeepSeek"
    assert getattr(model, "model_name", None) == "deepseek-flash"
