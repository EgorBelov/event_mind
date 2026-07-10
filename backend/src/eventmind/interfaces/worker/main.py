"""arq-worker: потребитель очереди + периодические задачи (cron).

Задачи:
- `process_outbox`      — доставка доменных событий аккаунтов (письма) (M1).
- `ingest_source`       — загрузка сырья одного источника в raw_events (M3).
- `normalize_raw_events`— LLM-нормализация пачки raw → events (M3).
- `send_user_digest`    — дайджест рекомендаций пользователю по каналам (M5).
- `schedule_digests`    — cron→queue: поставить дайджесты по частоте (M5).

Запуск: `arq eventmind.interfaces.worker.main.WorkerSettings`.
Композит-рут воркера: связывает use-case'ы с адаптерами (БД, LLM, embedding, SMTP, каналы).
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any, ClassVar

import structlog
from arq import cron

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
from eventmind.application.notifications.use_cases import ScheduleDigests, SendUserDigest
from eventmind.application.outbox.processor import OutboxProcessor
from eventmind.application.recommender.config import RecommenderConfig
from eventmind.application.recommender.ranker import HybridRanker
from eventmind.application.recommender.use_cases import GetRecommendations
from eventmind.config import Settings, get_settings, validate_or_exit
from eventmind.domain.recommender.weights import ScoringWeights
from eventmind.infrastructure.cache.redis_cache import RedisCache
from eventmind.infrastructure.db.engine import create_engine, create_session_factory
from eventmind.infrastructure.db.events_uow import SqlAlchemyEventsUnitOfWork
from eventmind.infrastructure.db.notifications import SqlAlchemyNotificationsUnitOfWork
from eventmind.infrastructure.db.outbox_store import SqlAlchemyOutboxStore
from eventmind.infrastructure.db.recommendation import SqlAlchemyRecommendationUnitOfWork
from eventmind.infrastructure.email.renderer import Jinja2EmailRenderer
from eventmind.infrastructure.email.smtp import SmtpEmailChannel
from eventmind.infrastructure.embedding.minilm import SentenceTransformerEmbeddingProvider
from eventmind.infrastructure.llm.providers import create_llm_chain
from eventmind.infrastructure.logging import configure_logging
from eventmind.infrastructure.notifications.registry import build_notification_channels
from eventmind.infrastructure.queue.arq_queue import ArqTaskQueue, redis_settings_from_url
from eventmind.infrastructure.recommender.candidate_generator import PgvectorCandidateGenerator
from eventmind.infrastructure.redis import create_redis
from eventmind.infrastructure.security.jwt import JwtTokenService
from eventmind.infrastructure.security.tokens import SystemClock
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

    # ── рекомендер + доставка (M4/M5) ──────────────────────────────────────
    redis = create_redis(settings)
    cache = RedisCache(redis)
    clock = SystemClock()

    def rec_uow_factory() -> SqlAlchemyRecommendationUnitOfWork:
        return SqlAlchemyRecommendationUnitOfWork(session_factory)

    def notif_uow_factory() -> SqlAlchemyNotificationsUnitOfWork:
        return SqlAlchemyNotificationsUnitOfWork(session_factory)

    get_recommendations = GetRecommendations(
        rec_uow_factory,
        PgvectorCandidateGenerator(session_factory),
        HybridRanker(),
        cache,
        clock,
        RecommenderConfig(
            candidate_limit=settings.reco_candidate_limit,
            result_limit=settings.reco_result_limit,
            cache_ttl_seconds=settings.reco_cache_ttl_seconds,
        ),
        ScoringWeights(),
    )
    # JWT-секрет для unsubscribe-ссылок должен совпадать с API (задать JWT_SECRET
    # в проде); в dev без него ссылки не провалидируются кросс-процессно.
    jwt_secret = settings.jwt_secret or secrets.token_urlsafe(48)
    token_service = JwtTokenService(jwt_secret)

    send_digest = SendUserDigest(
        notif_uow_factory,
        get_recommendations,
        build_notification_channels(settings),
        token_service,
        clock,
        settings.public_web_url,
    )
    schedule = ScheduleDigests(notif_uow_factory, ArqTaskQueue(settings.redis_url))

    return {
        "engine": engine,
        "redis": redis,
        "processor": outbox,
        "sources": build_source_registry(settings),
        "load_source": LoadSource(events_uow_factory, ArqTaskQueue(settings.redis_url)),
        "normalize": NormalizeRawEvents(
            events_uow_factory, EventNormalizer(llm), embedding, ingestion_config
        ),
        "send_digest": send_digest,
        "schedule": schedule,
    }


async def send_user_digest(ctx: dict[str, Any], user_id: int) -> dict[str, Any]:
    send: SendUserDigest = ctx["send_digest"]
    report = await send.execute(user_id)
    _logger.info(
        "digest_sent", user_id=user_id, delivered=report.delivered, skipped=report.skipped
    )
    return {"user_id": user_id, "delivered": report.delivered, "skipped": report.skipped}


async def schedule_digests(ctx: dict[str, Any], frequency: str = "daily") -> int:
    schedule: ScheduleDigests = ctx["schedule"]
    count = await schedule.execute(frequency=frequency)
    _logger.info("digests_scheduled", frequency=frequency, count=count)
    return count


async def cron_schedule_digests(ctx: dict[str, Any]) -> None:
    """Ежедневный cron: ставим daily-дайджесты; по понедельникам — ещё weekly."""
    await schedule_digests(ctx, "daily")
    if datetime.now(UTC).weekday() == 0:  # понедельник
        await schedule_digests(ctx, "weekly")


async def _on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    ctx.update(_build_resources(settings))
    _logger.info("worker_startup")


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()
    redis = ctx.get("redis")
    if redis is not None:
        await redis.aclose()
    _logger.info("worker_shutdown")


validate_or_exit(get_settings(), "worker")


class WorkerSettings:
    functions: ClassVar = [
        process_outbox,
        ingest_source,
        normalize_raw_events,
        send_user_digest,
        schedule_digests,
    ]
    on_startup = staticmethod(_on_startup)
    on_shutdown = staticmethod(_on_shutdown)
    redis_settings = redis_settings_from_url(get_settings().redis_url)
    # Дайджесты: cron раскладывает задачи в очередь раз в сутки (09:00 UTC).
    # arq дедуплицирует cron между воркерами — отдельный лидер-лок не нужен.
    cron_jobs: ClassVar[list[Any]] = [cron(cron_schedule_digests, hour={9}, minute={0})]
