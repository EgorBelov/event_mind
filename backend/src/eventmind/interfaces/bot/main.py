"""Точка входа Telegram-бота (aiogram 3, long-polling).

Композит-рут процесса bot: конфиг (fail-fast на пустой BOT_TOKEN/API-key),
`BotApiClient` (HTTP к API), FSM-хранилище (Redis — состояние онбординга и
показанного в ленте переживает перезапуск; без REDIS_URL — в памяти), меню
команд, регистрация роутера хендлеров. Бот — клиент API: не трогает БД.

Запуск: `python -m eventmind.interfaces.bot.main`.
"""
from __future__ import annotations

import asyncio

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand

from eventmind.config import Settings, get_settings, validate_or_exit
from eventmind.infrastructure.logging import configure_logging
from eventmind.interfaces.bot.api_client import BotApiClient
from eventmind.interfaces.bot.handlers import router

_logger = structlog.get_logger("eventmind.bot")


BOT_COMMANDS = [
    BotCommand(command="feed", description="Лента рекомендаций"),
    BotCommand(command="search", description="Поиск обычной фразой"),
    BotCommand(command="saved", description="Сохранённое"),
    BotCommand(command="settings", description="О себе, город, формат, дайджест"),
    BotCommand(command="reset", description="Начать разговор с помощником заново"),
    BotCommand(command="help", description="Что умеет бот"),
]


def build_storage(settings: Settings) -> BaseStorage:
    return RedisStorage.from_url(settings.redis_url) if settings.redis_url else MemoryStorage()


def build_dispatcher(settings: Settings) -> Dispatcher:
    """Собрать Dispatcher: внедрить api-клиент в workflow_data, включить роутер."""
    dp = Dispatcher(storage=build_storage(settings))
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
        await bot.set_my_commands(BOT_COMMANDS)
    except Exception as exc:  # меню — удобство, не причина не стартовать
        _logger.warning("bot_set_commands_failed", error=str(exc))
    try:
        await dp.start_polling(bot)
    finally:
        await dp.storage.close()
        await bot.session.close()
        _logger.info("bot_shutdown")


def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    validate_or_exit(settings, "bot")
    asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
