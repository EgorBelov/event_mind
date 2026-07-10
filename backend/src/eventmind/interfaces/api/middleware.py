"""HTTP-middleware: request-id + structlog-контекст + Prometheus-тайминги.

Одна строка структурированного лога на запрос
(`method path -> status`, rid, длительность). Request-id прокидывается в
заголовок ответа `X-Request-ID` и в contextvars (подхватывается structlog).
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from eventmind.infrastructure.telemetry.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
)

_REQUEST_ID_HEADER = "X-Request-ID"
_logger = structlog.get_logger("eventmind.access")

Handler = Callable[[Request], Awaitable[Response]]


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Присваивает request-id, логирует запрос, снимает тайминги/метрики."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        request_id = request.headers.get(_REQUEST_ID_HEADER) or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Шаблон маршрута (а не сырой путь) — чтобы не плодить кардинальность меток.
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - start
            path = _route_template(request)
            _logger.error(
                "request_failed",
                method=request.method,
                path=path,
                duration_ms=round(duration * 1000, 2),
            )
            HTTP_REQUESTS_TOTAL.labels(request.method, path, "500").inc()
            structlog.contextvars.clear_contextvars()
            raise

        duration = time.perf_counter() - start
        path = _route_template(request)
        response.headers[_REQUEST_ID_HEADER] = request_id

        HTTP_REQUESTS_TOTAL.labels(request.method, path, str(response.status_code)).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(request.method, path).observe(duration)

        log = _logger.info
        if response.status_code >= 500:
            log = _logger.error
        elif response.status_code >= 400:
            log = _logger.warning
        log(
            "request",
            method=request.method,
            path=path,
            status=response.status_code,
            duration_ms=round(duration * 1000, 2),
        )
        structlog.contextvars.clear_contextvars()
        return response


def _route_template(request: Request) -> str:
    """Шаблон маршрута (`/events/{id}`) вместо конкретного пути — низкая кардинальность."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return request.url.path
