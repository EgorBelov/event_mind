"""Fail-fast валидация конфигурации на boot'е.

Раньше пустой BOT_TOKEN / GROQ_API_KEY / DATABASE_URL давал кривые
рантайм-сбои далеко от точки боли. Здесь — единая проверка с понятным
сообщением и кодом выхода 78 (EX_CONFIG), которую делает каждый
энтрипоинт (API / scheduler / bot) под свой контекст.

Контексты:
- `api`        — нужен DATABASE_URL и GROQ_API_KEY. BOT_TOKEN опционален.
- `bot`        — нужен BOT_TOKEN и API_HOST. GROQ_API_KEY проксируется через API.
- `scheduler`  — нужен DATABASE_URL и API_HOST. BOT_TOKEN — для рассылки.

`strict=False` (по умолчанию) — пишем WARNING и продолжаем, удобно для
скриптов и dev-режима. `strict=True` — поднимаем `ConfigError` и зовущий
выходит с кодом.
"""
from __future__ import annotations

import logging
import sys
from typing import Literal

from app.core.config import settings

logger = logging.getLogger(__name__)

Context = Literal["api", "bot", "scheduler"]


class ConfigError(RuntimeError):
    """Поднимается при strict=True, если требуемые ключи пусты."""


_REQUIRED: dict[Context, tuple[str, ...]] = {
    "api": ("database_url", "groq_api_key"),
    "bot": ("bot_token", "api_host"),
    "scheduler": ("database_url", "api_host"),
}

_HUMAN_NAMES: dict[str, str] = {
    "database_url": "DATABASE_URL",
    "groq_api_key": "GROQ_API_KEY",
    "bot_token": "BOT_TOKEN",
    "api_host": "API_HOST",
    "api_shared_secret": "API_SHARED_SECRET",
}


def _is_set(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def validate_config(context: Context, *, strict: bool = True) -> list[str]:
    """Проверить settings под контекст. Возвращает список пустых ключей.

    При `strict=True` пустой список означает «ок», иначе — поднимаем
    ConfigError с человекочитаемой строкой.
    """
    required = _REQUIRED[context]
    missing: list[str] = [
        _HUMAN_NAMES.get(key, key.upper())
        for key in required
        if not _is_set(getattr(settings, key, None))
    ]

    # API_SHARED_SECRET — отдельный кейс: если пуст, авторизация выключена.
    # Это допустимо в dev, но на проде хотим явный WARNING.
    if context in ("api", "bot", "scheduler") and not _is_set(settings.api_shared_secret):
        logger.warning(
            "API_SHARED_SECRET пуст — авторизация API ОТКЛЮЧЕНА. "
            "Для прода обязательно задать общий секрет в .env."
        )

    if missing:
        msg = (
            f"Незаполнены обязательные переменные окружения для контекста "
            f"'{context}': {', '.join(missing)}. Проверь .env (см. .env.example)."
        )
        if strict:
            raise ConfigError(msg)
        logger.warning(msg)
    return missing


def validate_or_exit(context: Context) -> None:
    """Удобная обёртка для энтрипоинтов: пишет stderr и выходит 78 при сбое."""
    try:
        validate_config(context, strict=True)
    except ConfigError as e:
        # 78 = EX_CONFIG из <sysexits.h> — распространённый код «битый конфиг».
        sys.stderr.write(f"[config] {e}\n")
        sys.exit(78)
