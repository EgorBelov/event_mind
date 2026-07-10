"""Фабрика FastAPI-приложения + lifespan (graceful startup/shutdown).

lifespan открывает пул Postgres и клиент Redis, кладёт их в `app.state`,
на shutdown корректно дренирует. CORS настроен под веб-клиент. Все запросы
проходят через `RequestContextMiddleware` (request-id, логи, метрики).
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import structlog
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from eventmind import __version__
from eventmind.config import Settings, get_settings
from eventmind.infrastructure.logging import configure_logging
from eventmind.infrastructure.telemetry.tracing import setup_tracing
from eventmind.interfaces.api.container import build_container
from eventmind.interfaces.api.errors import install_error_handlers
from eventmind.interfaces.api.middleware import RequestContextMiddleware
from eventmind.interfaces.api.routers import (
    admin,
    auth,
    channels,
    events,
    health,
    ingestion,
    notifications,
    recommendations,
    users,
    v1,
)

_logger = structlog.get_logger("eventmind.api")


Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def _build_lifespan(settings: Settings) -> Lifespan:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = build_container(settings)
        app.state.container = container
        # engine/redis наружу для health-роутера (readiness-пинги).
        app.state.engine = container.engine
        app.state.redis = container.redis
        _logger.info("api_startup", environment=settings.environment, version=__version__)
        try:
            yield
        finally:
            await container.aclose()
            _logger.info("api_shutdown")

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    """Собрать FastAPI-приложение. Точка сборки (composition root) API-процесса."""
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)

    app = FastAPI(
        title="EventMind API",
        version=__version__,
        lifespan=_build_lifespan(settings),
    )
    app.state.settings = settings

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(v1.router)
    app.include_router(auth.router)
    app.include_router(channels.router)
    app.include_router(admin.router)
    app.include_router(ingestion.router)
    app.include_router(recommendations.router)
    app.include_router(notifications.router)
    app.include_router(events.router)
    app.include_router(users.router)

    setup_tracing(app, settings)
    return app
