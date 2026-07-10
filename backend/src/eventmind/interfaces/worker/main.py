"""arq-worker: потребитель очереди.

Задачи:
- `process_outbox`      — доставка доменных событий аккаунтов (письма) (M1).
- `ingest_source`       — загрузка сырья одного источника в raw_events (M3).
- `normalize_raw_events`— LLM-нормализация пачки raw → events (M3).

Запуск: `arq eventmind.interfaces.worker.main.WorkerSettings`.
Композит-рут воркера: связывает use-case'ы с адаптерами (БД, LLM, embedding, SMTP).
"""
from __future__ import annotations

from typing import Any, ClassVar

import structlog

from eventmind.application.accounts.email_handlers import (
    make_password_reset_handler,
    make_user_registered_handler,
)
from eventmind.application.ingestion.config import IngestionConfig
from eventmind.application.ingestion.normalizer import EventNormalizer
from eventmind.application.ingestion.use_cases import (
    LoadSource,
    NormalizeRawEvents,
)
from eventmind.application.outbox.processor import OutboxProcessor
from eventmind.config import Settings, get_settings, validate_or_exit
from eventmind.infrastructure.db.engine import create_engine, create_session_factory
from eventmind.infrastructure.db.events_uow import SqlAlchemyEventsUnitOfWork
from eventmind.infrastructure.db.outbox_store import SqlAlchemyOutboxStore
from eventmind.infrastructure.email.renderer import Jinja2EmailRenderer
from eventmind.infrastructure.email.smtp import SmtpEmailChannel
from eventmind.infrastructure.embedding.minilm import SentenceTransformerEmbeddingProvider
from eventmind.infrastructure.llm.providers import create_llm_chain
from eventmind.infrastructure.logging import configure_logging
from eventmind.infrastructure.queue.arq_queue import ArqTaskQueue, redis_settings_from_url
from eventmind.infrastructure.sources.registry import build_source_registry

_logger = structlog.get_logger("eventmind.worker")


# ── задачи ────────────────────────────────────────────────────────────────────
async def process_outbox(ctx: dict[str, Any]) -> int:
    processor: OutboxProcessor = ctx["processor"]
    count = await processor.process_pending()
    if count:
        _logger.info("outbox_processed", count=count)
    return count


async def ingest_source(ctx: dict[str, Any], source: str, limit: int = 20) -> dict[str, Any]:
    sources = ctx["sources"]
    event_source = sources.get(source)
    if event_source is None:
        _logger.warning("ingest_unknown_source", source=source)
        return {"source": source, "added": 0}
    load: LoadSource = ctx["load_source"]
    result = await load.execute(event_source, limit=limit)
    _logger.info("ingest_source_done", source=source, added=result.added)
    return {"source": source, "added": result.added, "fetched": result.fetched}


async def normalize_raw_events(ctx: dict[str, Any], limit: int | None = None) -> dict[str, Any]:
    normalize: NormalizeRawEvents = ctx["normalize"]
    result = await normalize.execute(limit=limit)
    if result.processed:
        _logger.info(
            "normalize_done",
            processed=result.processed,
            events=result.events_created,
            non_it=result.non_it,
            failed=result.failed,
        )
    return {
        "processed": result.processed,
        "events_created": result.events_created,
        "non_it": result.non_it,
        "failed": result.failed,
    }


# ── жизненный цикл воркера ─────────────────────────────────────────────────────
def _build_resources(settings: Settings) -> dict[str, Any]:
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    def events_uow_factory() -> SqlAlchemyEventsUnitOfWork:
        return SqlAlchemyEventsUnitOfWork(session_factory)

    channel = SmtpEmailChannel(settings)
    renderer = Jinja2EmailRenderer(settings.public_web_url)
    outbox = OutboxProcessor(
        SqlAlchemyOutboxStore(session_factory),
        {
            "user.registered": make_user_registered_handler(
                channel, renderer, settings.public_web_url
            ),
            "password.reset_requested": make_password_reset_handler(
                channel, renderer, settings.public_web_url
            ),
        },
    )

    llm = create_llm_chain(settings)
    embedding = SentenceTransformerEmbeddingProvider(
        model_name=settings.embedding_model_name,
        dimension=settings.embedding_dimension,
        cache_size=settings.embedding_cache_size,
    )
    ingestion_config = IngestionConfig(
        normalize_batch_size=settings.normalize_batch_size,
        max_normalize_retries=settings.max_normalize_retries,
    )
    return {
        "engine": engine,
        "processor": outbox,
        "sources": build_source_registry(settings),
        "load_source": LoadSource(events_uow_factory, ArqTaskQueue(settings.redis_url)),
        "normalize": NormalizeRawEvents(
            events_uow_factory, EventNormalizer(llm), embedding, ingestion_config
        ),
    }


async def _on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    ctx.update(_build_resources(settings))
    _logger.info("worker_startup")


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()
    _logger.info("worker_shutdown")


validate_or_exit(get_settings(), "worker")


class WorkerSettings:
    functions: ClassVar = [process_outbox, ingest_source, normalize_raw_events]
    on_startup = staticmethod(_on_startup)
    on_shutdown = staticmethod(_on_shutdown)
    redis_settings = redis_settings_from_url(get_settings().redis_url)
    cron_jobs: ClassVar[list[Any]] = []
