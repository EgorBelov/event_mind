"""Точка входа Telegram-бота (aiogram 3, long-polling).

Композит-рут процесса bot: конфиг (fail-fast на пустой BOT_TOKEN/API-key),
`BotApiClient` (HTTP к API), регистрация роутера хендлеров. Бот — вторичный
клиент: не трогает БД, всё делает через API.

Запуск: `python -m eventmind.interfaces.bot.main`.
"""
from __future__ import annotations

import asyncio

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from eventmind.config import Settings, get_settings, validate_or_exit
from eventmind.infrastructure.logging import configure_logging
from eventmind.interfaces.bot.api_client import BotApiClient
from eventmind.interfaces.bot.handlers import router

_logger = structlog.get_logger("eventmind.bot")


def build_dispatcher(settings: Settings) -> Dispatcher:
    """Собрать Dispatcher: внедрить api-клиент в workflow_data, включить роутер."""
    dp = Dispatcher()
    dp["api"] = BotApiClient(settings.api_internal_url, settings.api_shared_secret)
    dp.include_router(router)
    return dp


async def _run(settings: Settings) -> None:
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = build_dispatcher(settings)
    _logger.info("bot_startup", api=settings.api_internal_url)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        _logger.info("bot_shutdown")


def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    validate_or_exit(settings, "bot")
    asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
