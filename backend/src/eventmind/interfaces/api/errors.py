"""Единый формат ошибок API + маппинг доменных ошибок в HTTP-статусы.

Ответ: `{"error": {"code": ..., "message": ...}}`. Доменные ошибки
(`domain.accounts.errors`) не знают про HTTP — транслируем их здесь.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
)

from eventmind.domain.accounts.errors import (
    AccountInactive,
    ChannelAlreadyLinked,
    DomainError,
    EmailAlreadyRegistered,
    EmailNotVerified,
    InvalidCredentials,
    TokenInvalidOrExpired,
    UserNotFound,
)


class ApiError(Exception):
    """Явная ошибка API с кодом и HTTP-статусом (для auth/валидации транспорта)."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


# Доменная ошибка → (HTTP-статус, машинный код).
_DOMAIN_MAP: dict[type[DomainError], tuple[int, str]] = {
    EmailAlreadyRegistered: (HTTP_409_CONFLICT, "email_already_registered"),
    InvalidCredentials: (HTTP_401_UNAUTHORIZED, "invalid_credentials"),
    UserNotFound: (HTTP_404_NOT_FOUND, "user_not_found"),
    AccountInactive: (HTTP_403_FORBIDDEN, "account_inactive"),
    EmailNotVerified: (HTTP_403_FORBIDDEN, "email_not_verified"),
    ChannelAlreadyLinked: (HTTP_409_CONFLICT, "channel_already_linked"),
    TokenInvalidOrExpired: (HTTP_400_BAD_REQUEST, "token_invalid_or_expired"),
}


def _error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content=_error_body(exc.code, exc.message)
        )

    @app.exception_handler(DomainError)
    async def _handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        status_code, code = _DOMAIN_MAP.get(type(exc), (HTTP_400_BAD_REQUEST, "domain_error"))
        return JSONResponse(status_code=status_code, content=_error_body(code, str(exc)))

    @app.exception_handler(ValueError)
    async def _handle_value_error(_: Request, exc: ValueError) -> JSONResponse:
        # Например, некорректный email из доменного VO в обход pydantic.
        return JSONResponse(
            status_code=HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_body("validation_error", str(exc)),
        )
