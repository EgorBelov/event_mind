"""Liveness/readiness-проба.

- `/health` — liveness: процесс жив (без внешних зависимостей).
- `/ready`  — readiness: доступны Postgres и Redis. 503 при недоступности,
  чтобы k8s/оркестратор не слал трафик на неготовый под.
- `/metrics` — срез Prometheus.
"""
from __future__ import annotations

from fastapi import APIRouter, Response
from starlette.requests import Request
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE

from eventmind.infrastructure.db.engine import ping_db
from eventmind.infrastructure.redis import ping_redis
from eventmind.infrastructure.telemetry.metrics import render_metrics

router = APIRouter(tags=["ops"])


@router.get("/health", summary="Liveness")
async def health() -> dict[str, str]:
    """Процесс жив. Не трогает внешние зависимости."""
    return {"status": "ok"}


@router.get("/ready", summary="Readiness (Postgres + Redis)")
async def ready(request: Request, response: Response) -> dict[str, object]:
    """Готовность обслуживать трафик: пингует Postgres и Redis."""
    engine = request.app.state.engine
    redis = request.app.state.redis
    db_ok = await ping_db(engine)
    redis_ok = await ping_redis(redis)
    ready_ = db_ok and redis_ok
    if not ready_:
        response.status_code = HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready_ else "not_ready",
        "checks": {"database": db_ok, "redis": redis_ok},
    }


@router.get("/metrics", summary="Prometheus-метрики", include_in_schema=False)
async def metrics() -> Response:
    """Текстовый экспорт Prometheus."""
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)
