"""Конфигурация v2 + fail-fast валидация на boot'е каждого процесса.

Единый `Settings` (pydantic-settings) читает `.env`/окружение. Каждый
энтрипоинт (api/worker/scheduler/bot) под свой контекст зовёт
`validate_or_exit(ctx)`: при отсутствии required-полей процесс падает с
кодом **78** (EX_CONFIG из <sysexits.h>) и понятным сообщением — а не
кривым рантайм-сбоем далеко от точки боли.

Идея портирована из `legacy/app/core/config_validate.py`, но контексты и
поля переосмыслены под account-центричную мультиканальную архитектуру.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Context = Literal["api", "worker", "scheduler", "bot"]


class Settings(BaseSettings):
    """Все настройки v2. Значения по умолчанию рассчитаны на dev-compose."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── окружение ────────────────────────────────────────────────────────
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = True  # structlog JSON; в dev можно false для человекочитаемости

    # ── хранилища ────────────────────────────────────────────────────────
    # async-драйвер (asyncpg). В dev-compose указывает на сервис postgres.
    database_url: str = "postgresql+asyncpg://eventmind:eventmind@postgres:5432/eventmind"
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_pool_recycle: int = 1500  # Supabase/pooler режет idle ~5 мин
    redis_url: str = "redis://redis:6379/0"

    # ── api ──────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # CORS под веб-клиент (Next.js). Список origin'ов через запятую.
    cors_origins: str = "http://localhost:3000"
    # Внутренний shared-secret для вызовов worker↔api, bot↔api (hmac.compare_digest).
    # Пустой = open-mode (только dev).
    api_shared_secret: str = ""
    # Секрет подписи пользовательских JWT (M1). Пустой валиден только в dev.
    jwt_secret: str = ""

    # ── наблюдаемость ────────────────────────────────────────────────────
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = ""
    service_name: str = "eventmind-api"

    # ── LLM (M2): цепочка Gemini → Groq70b → Groq8b за LLMGateway ─────────
    google_api_key: str = ""
    google_model: str = ""  # пусто — берём первый кандидат/автопроба
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_fallback_model: str = "llama-3.1-8b-instant"
    llm_temperature: float = 0.3
    llm_timeout_seconds: float = 45.0
    # circuit-breaker + per-provider cooldown (см. infrastructure/llm)
    llm_breaker_threshold: int = 5
    llm_breaker_cooldown_seconds: float = 120.0
    llm_provider_cooldown_seconds: float = 600.0
    llm_provider_fail_threshold: int = 2

    # ── эмбеддинги (M2): MiniLM-384, multilingual/русский ────────────────
    embedding_model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dimension: int = 384
    embedding_cache_size: int = 4096

    # ── ingestion (M3) ───────────────────────────────────────────────────
    # RSS-ленты через запятую (пусто — источник rss отключён).
    rss_feeds: str = ""
    ingest_default_limit: int = 20
    normalize_batch_size: int = 20
    max_normalize_retries: int = 3

    # ── рекомендер (M4) ──────────────────────────────────────────────────
    reco_candidate_limit: int = 100
    reco_result_limit: int = 20
    reco_cache_ttl_seconds: int = 900

    # ── email-канал (M1/M5): dev→Mailhog, prod→Yandex/Mail.ru SMTP ───────
    smtp_host: str = "mailhog"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False  # Mailhog — без TLS; Yandex/Mail.ru — true
    smtp_use_ssl: bool = False  # Mail.ru поддерживает SSL 465
    email_from: str = "EventMind <noreply@eventmind.local>"

    # ── telegram (M7) ────────────────────────────────────────────────────
    bot_token: str = ""
    telegram_bot_username: str = ""  # для deep-link https://t.me/<username>?start=<token>
    # Публичный базовый URL веба/бота для deep-link'ов и unsubscribe-ссылок.
    public_web_url: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


# Обязательные поля под каждый контекст (имена атрибутов Settings).
_REQUIRED: dict[Context, tuple[str, ...]] = {
    "api": ("database_url", "redis_url"),
    "worker": ("database_url", "redis_url"),
    "scheduler": ("database_url", "redis_url"),
    "bot": ("bot_token", "api_shared_secret"),
}

_HUMAN_NAMES: dict[str, str] = {
    "database_url": "DATABASE_URL",
    "redis_url": "REDIS_URL",
    "bot_token": "BOT_TOKEN",
    "api_shared_secret": "API_SHARED_SECRET",
    "jwt_secret": "JWT_SECRET",
}


class ConfigError(RuntimeError):
    """Поднимается, если под контекст пусты обязательные поля."""


def _is_set(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def validate_config(settings: Settings, context: Context) -> list[str]:
    """Вернуть список НЕзаполненных обязательных полей под контекст.

    Пустой список — конфиг валиден. Побочно поднимает `ConfigError`, если
    что-то критичное пусто (см. `validate_or_exit`).
    """
    missing = [
        _HUMAN_NAMES.get(key, key.upper())
        for key in _REQUIRED[context]
        if not _is_set(getattr(settings, key, None))
    ]
    if missing:
        raise ConfigError(
            f"Незаполнены обязательные переменные окружения для контекста "
            f"'{context}': {', '.join(missing)}. Проверь .env (см. .env.example)."
        )
    return missing


def validate_or_exit(settings: Settings, context: Context) -> None:
    """Энтрипоинт-обёртка: при битом конфиге пишет stderr и выходит с кодом 78."""
    try:
        validate_config(settings, context)
    except ConfigError as exc:
        sys.stderr.write(f"[config] {exc}\n")
        raise SystemExit(78) from exc

    # На проде пустой JWT/секрет — не падаем, но это опасно: пусть будет видно.
    if settings.environment == "prod":
        prod_secrets = (
            ("api_shared_secret", "API_SHARED_SECRET"),
            ("jwt_secret", "JWT_SECRET"),
        )
        for attr, human in prod_secrets:
            if not _is_set(getattr(settings, attr)):
                sys.stderr.write(
                    f"[config] ВНИМАНИЕ: {human} пуст в prod — это небезопасно.\n"
                )


@lru_cache
def get_settings() -> Settings:
    """Кэшированный singleton настроек (читается один раз за процесс)."""
    return Settings()
