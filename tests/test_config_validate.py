"""Тесты fail-fast валидации конфигурации."""
import pytest

from app.core.config import settings
from app.core.config_validate import ConfigError, validate_config


def test_api_context_passes_when_all_set(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "sqlite:///./x.db")
    monkeypatch.setattr(settings, "groq_api_key", "some-key")
    assert validate_config("api", strict=True) == []


def test_api_context_fails_without_db(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "groq_api_key", "some-key")
    with pytest.raises(ConfigError) as exc:
        validate_config("api", strict=True)
    assert "DATABASE_URL" in str(exc.value)


def test_bot_context_requires_bot_token(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", "")
    monkeypatch.setattr(settings, "api_host", "http://localhost:8000")
    with pytest.raises(ConfigError) as exc:
        validate_config("bot", strict=True)
    assert "BOT_TOKEN" in str(exc.value)


def test_scheduler_context_requires_api_host(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "sqlite:///./x.db")
    monkeypatch.setattr(settings, "api_host", "")
    with pytest.raises(ConfigError) as exc:
        validate_config("scheduler", strict=True)
    assert "API_HOST" in str(exc.value)


def test_non_strict_returns_missing_list(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "groq_api_key", "")
    missing = validate_config("api", strict=False)
    assert "DATABASE_URL" in missing
    assert "GROQ_API_KEY" in missing
