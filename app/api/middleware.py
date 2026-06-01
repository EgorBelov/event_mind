"""ASGI middleware и exception handlers для FastAPI.

Цели:
- Полные тайминги по каждому запросу с request-id'ом — иначе тяжело
  понять, кто именно тормозит под Supabase.
- 4xx не шумят tracebacks'ом в логах: business-`HTTPException(404)` — это
  нормальная ветка, не ERROR.
- 5xx — наоборот, явный ERROR с трейсом.
- Shared-secret авторизация: на проде эндпоинты, принимающие telegram_id
  в пути, открыты любому. Минимум — заголовок `X-API-Key`, известный
  только боту и API.
"""
from __future__ import annotations

import hmac
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

logger = logging.getLogger("eventmind.access")

# Эти пути всегда открыты — иначе мониторинг и `/docs` не работают.
_PUBLIC_PATHS: tuple[str, ...] = (
    "/", "/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico",
)
_PUBLIC_PREFIXES: tuple[str, ...] = ("/docs/", "/redoc/")


def _is_public_path(path: str) -> bool:
    return path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Shared-secret авторизация через заголовок `X-API-Key`.

    Включается только если `settings.api_shared_secret` непуст — иначе
    дев-окружение и тесты работали бы без всякой конфигурации.

    Сверка — через `hmac.compare_digest` (constant-time), чтобы тайминговая
    атака не подсказала длину ключа.
    """

    async def dispatch(self, request: Request, call_next):
        secret = settings.api_shared_secret
        if not secret or _is_public_path(request.url.path):
            return await call_next(request)
        provided = request.headers.get("x-api-key", "")
        if not hmac.compare_digest(provided, secret):
            rid = getattr(request.state, "request_id", "-")
            logger.warning(
                "API key check failed on %s %s (rid=%s)",
                request.method, request.url.path, rid,
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "missing or invalid X-API-Key", "request_id": rid},
                headers={"X-Request-ID": rid} if rid != "-" else {},
            )
        return await call_next(request)


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Лог одной строки на запрос: method, path, status, duration_ms, request_id.

    Request-ID берётся из заголовка X-Request-ID (если клиент его поставил —
    можно сквозно трейсить), иначе генерируется здесь. Сам ID кладётся
    в ответ — клиент видит, по какому ID искать в логах.
    """

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = rid
        t0 = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            # Логируем и пробрасываем — exception handler ниже превратит в 500.
            dur_ms = round((time.monotonic() - t0) * 1000, 2)
            logger.exception(
                "%s %s -> 500 (rid=%s, %.2fms, UNHANDLED)",
                request.method, request.url.path, rid, dur_ms,
            )
            raise
        dur_ms = round((time.monotonic() - t0) * 1000, 2)
        status = response.status_code
        # Уровень по коду: 5xx — ERROR, 4xx — WARNING, остальное — INFO.
        if status >= 500:
            log_fn = logger.error
        elif status >= 400:
            log_fn = logger.warning
        else:
            log_fn = logger.info
        log_fn(
            "%s %s -> %d (rid=%s, %.2fms)",
            request.method, request.url.path, status, rid, dur_ms,
        )
        response.headers["X-Request-ID"] = rid
        return response


def install_middleware_and_handlers(app: FastAPI) -> None:
    """Подключить middleware и handlers — один вызов из main.py.

    Порядок add_middleware у Starlette — обратный к вызовам: последний
    добавленный обрабатывается ПЕРВЫМ. Хотим: сначала RequestLog (чтобы
    rid был доступен в API-key check), потом API-key. Значит ApiKey
    добавляем первым, RequestLog вторым.
    """
    app.add_middleware(ApiKeyMiddleware)
    app.add_middleware(RequestLogMiddleware)

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException):
        # Для 4xx — короткая WARNING без traceback; 5xx — ERROR с traceback.
        rid = getattr(request.state, "request_id", "-")
        if 400 <= exc.status_code < 500:
            logger.warning(
                "HTTP %d on %s %s (rid=%s): %s",
                exc.status_code, request.method, request.url.path, rid, exc.detail,
            )
        else:
            logger.exception(
                "HTTP %d on %s %s (rid=%s): %s",
                exc.status_code, request.method, request.url.path, rid, exc.detail,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "request_id": rid},
            headers={"X-Request-ID": rid},
        )
