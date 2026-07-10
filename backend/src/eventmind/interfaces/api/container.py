"""Композит-рут API: контейнер синглтонов (адаптеры портов) на процесс.

Собирается в lifespan приложения. Зависимости (`dependencies.py`) достают
контейнер из `app.state` и строят из него use-case'ы.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from eventmind.application.accounts.config import AccountsConfig
from eventmind.application.ingestion.config import IngestionConfig
from eventmind.application.ingestion.normalizer import EventNormalizer
from eventmind.application.ports.embedding import EmbeddingProvider
from eventmind.application.ports.events import EventsUnitOfWork
from eventmind.application.ports.security import (
    Clock,
    PasswordHasher,
    SecretTokenGenerator,
    TokenService,
)
from eventmind.application.ports.sources import EventSource
from eventmind.application.ports.uow import UnitOfWork
from eventmind.config import Settings
from eventmind.infrastructure.db.engine import create_engine, create_session_factory
from eventmind.infrastructure.db.events_uow import SqlAlchemyEventsUnitOfWork
from eventmind.infrastructure.db.uow import SqlAlchemyUnitOfWork
from eventmind.infrastructure.embedding.minilm import SentenceTransformerEmbeddingProvider
from eventmind.infrastructure.llm.chain import LLMChain
from eventmind.infrastructure.llm.providers import create_llm_chain
from eventmind.infrastructure.queue.arq_queue import ArqTaskQueue
from eventmind.infrastructure.redis import RedisClient, create_redis
from eventmind.infrastructure.security.jwt import JwtTokenService
from eventmind.infrastructure.security.password import Argon2PasswordHasher
from eventmind.infrastructure.security.tokens import (
    Sha256SecretTokenGenerator,
    SystemClock,
)
from eventmind.infrastructure.sources.registry import build_source_registry

_logger = structlog.get_logger("eventmind.api")


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    redis: RedisClient
    task_queue: ArqTaskQueue
    password_hasher: PasswordHasher
    token_service: TokenService
    token_generator: SecretTokenGenerator
    clock: Clock
    accounts_config: AccountsConfig
    llm: LLMChain
    embedding: EmbeddingProvider
    sources: dict[str, EventSource]
    normalizer: EventNormalizer
    ingestion_config: IngestionConfig

    def uow_factory(self) -> UnitOfWork:
        return SqlAlchemyUnitOfWork(self.session_factory)

    def events_uow_factory(self) -> EventsUnitOfWork:
        return SqlAlchemyEventsUnitOfWork(self.session_factory)

    async def aclose(self) -> None:
        await self.task_queue.aclose()
        await self.redis.aclose()
        await self.engine.dispose()


def build_container(settings: Settings) -> Container:
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    redis = create_redis(settings)

    jwt_secret = settings.jwt_secret
    if not jwt_secret:
        # Dev-режим без JWT_SECRET: эфемерный секрет (токены живут до рестарта).
        jwt_secret = secrets.token_urlsafe(48)
        _logger.warning("jwt_secret_empty_using_ephemeral")

    llm = create_llm_chain(settings)

    return Container(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        redis=redis,
        task_queue=ArqTaskQueue(settings.redis_url),
        password_hasher=Argon2PasswordHasher(),
        token_service=JwtTokenService(jwt_secret),
        token_generator=Sha256SecretTokenGenerator(),
        clock=SystemClock(),
        accounts_config=AccountsConfig(),
        llm=llm,
        embedding=SentenceTransformerEmbeddingProvider(
            model_name=settings.embedding_model_name,
            dimension=settings.embedding_dimension,
            cache_size=settings.embedding_cache_size,
        ),
        sources=build_source_registry(settings),
        normalizer=EventNormalizer(llm),
        ingestion_config=IngestionConfig(
            normalize_batch_size=settings.normalize_batch_size,
            max_normalize_retries=settings.max_normalize_retries,
        ),
    )
