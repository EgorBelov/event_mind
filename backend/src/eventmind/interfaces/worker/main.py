"""arq-worker: потребитель очереди. В M1 — обработка outbox (рассылка писем).

Запуск: `arq eventmind.interfaces.worker.main.WorkerSettings`.
Композит-рут воркера: связывает `OutboxProcessor` с обработчиками событий
(письма верификации/сброса) и адаптерами (SMTP EmailChannel, Jinja-renderer).
Наполняется ingestion/нормализацией/backfill'ом в M3.
"""
from __future__ import annotations

from typing import Any, ClassVar

import structlog

from eventmind.application.accounts.email_handlers import (
    make_password_reset_handler,
    make_user_registered_handler,
)
from eventmind.application.outbox.processor import OutboxProcessor
from eventmind.config import Settings, get_settings, validate_or_exit
from eventmind.infrastructure.db.engine import create_engine, create_session_factory
from eventmind.infrastructure.db.outbox_store import SqlAlchemyOutboxStore
from eventmind.infrastructure.email.renderer import Jinja2EmailRenderer
from eventmind.infrastructure.email.smtp import SmtpEmailChannel
from eventmind.infrastructure.logging import configure_logging
from eventmind.infrastructure.queue.arq_queue import redis_settings_from_url

_logger = structlog.get_logger("eventmind.worker")


def _build_processor(settings: Settings) -> tuple[OutboxProcessor, Any]:
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    store = SqlAlchemyOutboxStore(session_factory)
    channel = SmtpEmailChannel(settings)
    renderer = Jinja2EmailRenderer(settings.public_web_url)
    handlers = {
        "user.registered": make_user_registered_handler(
            channel, renderer, settings.public_web_url
        ),
        "password.reset_requested": make_password_reset_handler(
            channel, renderer, settings.public_web_url
        ),
    }
    return OutboxProcessor(store, handlers), engine


async def process_outbox(ctx: dict[str, Any]) -> int:
    """Обработать необработанные события из outbox (рассылка писем)."""
    processor: OutboxProcessor = ctx["processor"]
    count = await processor.process_pending()
    if count:
        _logger.info("outbox_processed", count=count)
    return count


async def _on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    processor, engine = _build_processor(settings)
    ctx["processor"] = processor
    ctx["engine"] = engine
    _logger.info("worker_startup")


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()
    _logger.info("worker_shutdown")


validate_or_exit(get_settings(), "worker")


class WorkerSettings:
    """Конфиг arq-воркера."""

    functions: ClassVar = [process_outbox]
    on_startup = staticmethod(_on_startup)
    on_shutdown = staticmethod(_on_shutdown)
    redis_settings = redis_settings_from_url(get_settings().redis_url)
    # Периодическая подчистка outbox — страховка, если enqueue из API потерялся.
    cron_jobs: ClassVar[list[Any]] = []
