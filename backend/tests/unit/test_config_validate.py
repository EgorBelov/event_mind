"""Unit: fail-fast валидация конфига под контексты + выход с кодом 78."""
from __future__ import annotations

import pytest

from eventmind.config import ConfigError, Settings, validate_config, validate_or_exit


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://u:p@h:5432/db",
        "redis_url": "redis://h:6379/0",
        "bot_token": "123:abc",
        "api_shared_secret": "secret",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_api_context_ok_when_db_and_redis_set() -> None:
    assert validate_config(_settings(), "api") == []


def test_api_context_raises_when_db_missing() -> None:
    with pytest.raises(ConfigError) as exc:
        validate_config(_settings(database_url=""), "api")
    assert "DATABASE_URL" in str(exc.value)


def test_bot_context_requires_token_and_secret() -> None:
    with pytest.raises(ConfigError) as exc:
        validate_config(_settings(bot_token="", api_shared_secret=""), "bot")
    assert "BOT_TOKEN" in str(exc.value)
    assert "API_SHARED_SECRET" in str(exc.value)


def test_validate_or_exit_exits_78_on_bad_config() -> None:
    with pytest.raises(SystemExit) as exc:
        validate_or_exit(_settings(redis_url=""), "worker")
    assert exc.value.code == 78


def test_validate_or_exit_passes_on_good_config() -> None:
    # Не должно бросать/выходить.
    validate_or_exit(_settings(), "scheduler")


def test_cors_origin_list_parsing() -> None:
    s = _settings(cors_origins="http://a.com, http://b.com ,")
    assert s.cors_origin_list == ["http://a.com", "http://b.com"]
