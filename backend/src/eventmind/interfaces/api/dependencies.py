"""FastAPI-зависимости: доступ к контейнеру, текущий пользователь, внутренний API-key.

Провайдеры use-case'ов собирают их из синглтонов контейнера. Аутентификация
пользователя — по access-JWT из httpOnly-cookie (или заголовка Authorization).
Внутренние вызовы (bot↔api) — по `X-API-Key` (hmac.compare_digest).
"""
from __future__ import annotations

import hmac
from typing import Annotated

import jwt
from fastapi import Depends, Header, Request
from fastapi.security.utils import get_authorization_scheme_param
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from eventmind.application.accounts.use_cases import (
    AuthenticateUser,
    AuthenticateWithGoogle,
    ConfirmTelegramLink,
    CreateTelegramLinkToken,
    RegisterUser,
    RequestPasswordReset,
    ResetPassword,
    UpdatePreferences,
    UpdateProfile,
    VerifyEmail,
)
from eventmind.application.ingestion.use_cases import (
    GetIngestionStatus,
    LoadAllSources,
    LoadSource,
    NormalizeRawEvents,
)
from eventmind.application.notifications.use_cases import (
    ListInbox,
    MarkNotificationRead,
    Unsubscribe,
)
from eventmind.application.recommender.use_cases import (
    GetRecommendations,
    RecordInteraction,
)
from eventmind.application.search.use_cases import GetEvent, NlSearch
from eventmind.domain.accounts.entities import User
from eventmind.domain.recommender.weights import ScoringWeights
from eventmind.interfaces.api.container import Container
from eventmind.interfaces.api.errors import ApiError

ACCESS_COOKIE_NAME = "eventmind_access"
REFRESH_COOKIE_NAME = "eventmind_refresh"


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


# ── провайдеры use-case'ов ───────────────────────────────────────────────────
def get_register_user(container: ContainerDep) -> RegisterUser:
    return RegisterUser(
        container.uow_factory,
        container.password_hasher,
        container.token_generator,
        container.clock,
        container.task_queue,
        container.accounts_config,
    )


def get_verify_email(container: ContainerDep) -> VerifyEmail:
    return VerifyEmail(container.uow_factory, container.token_generator, container.clock)


def get_authenticate_user(container: ContainerDep) -> AuthenticateUser:
    return AuthenticateUser(container.uow_factory, container.password_hasher)


def get_request_password_reset(container: ContainerDep) -> RequestPasswordReset:
    return RequestPasswordReset(
        container.uow_factory,
        container.token_generator,
        container.clock,
        container.task_queue,
        container.accounts_config,
    )


def get_reset_password(container: ContainerDep) -> ResetPassword:
    return ResetPassword(
        container.uow_factory,
        container.token_generator,
        container.password_hasher,
        container.clock,
    )


def get_create_telegram_link(container: ContainerDep) -> CreateTelegramLinkToken:
    return CreateTelegramLinkToken(
        container.uow_factory, container.token_generator, container.clock, container.accounts_config
    )


def get_confirm_telegram_link(container: ContainerDep) -> ConfirmTelegramLink:
    return ConfirmTelegramLink(
        container.uow_factory, container.token_generator, container.clock
    )


def get_authenticate_with_google(container: ContainerDep) -> AuthenticateWithGoogle:
    return AuthenticateWithGoogle(container.uow_factory, container.google_verifier)


def get_update_profile(container: ContainerDep) -> UpdateProfile:
    return UpdateProfile(container.uow_factory)


def get_update_preferences(container: ContainerDep) -> UpdatePreferences:
    return UpdatePreferences(container.uow_factory)


# ── ingestion (M3) ───────────────────────────────────────────────────────────
def get_load_source(container: ContainerDep) -> LoadSource:
    return LoadSource(container.events_uow_factory, container.task_queue)


def get_load_all(container: ContainerDep) -> LoadAllSources:
    return LoadAllSources(container.sources, get_load_source(container))


def get_normalize_raw_events(container: ContainerDep) -> NormalizeRawEvents:
    return NormalizeRawEvents(
        container.events_uow_factory,
        container.normalizer,
        container.embedding,
        container.ingestion_config,
    )


def get_ingestion_status(container: ContainerDep) -> GetIngestionStatus:
    return GetIngestionStatus(container.events_uow_factory)


# ── рекомендер (M4) ──────────────────────────────────────────────────────────
def get_recommendations_uc(container: ContainerDep) -> GetRecommendations:
    return GetRecommendations(
        container.recommendation_uow_factory,
        container.candidate_generator,
        container.ranker,
        container.cache,
        container.clock,
        container.recommender_config,
        ScoringWeights(),
    )


def get_record_interaction_uc(container: ContainerDep) -> RecordInteraction:
    return RecordInteraction(container.recommendation_uow_factory, container.cache)


# ── поиск событий (M6) ───────────────────────────────────────────────────────
def get_nl_search(container: ContainerDep) -> NlSearch:
    return NlSearch(container.llm, container.search_repository, container.clock)


def get_event_uc(container: ContainerDep) -> GetEvent:
    return GetEvent(container.search_repository)


# ── уведомления (M5) ─────────────────────────────────────────────────────────
def get_list_inbox(container: ContainerDep) -> ListInbox:
    return ListInbox(container.notifications_uow_factory)


def get_mark_read(container: ContainerDep) -> MarkNotificationRead:
    return MarkNotificationRead(container.notifications_uow_factory)


def get_unsubscribe(container: ContainerDep) -> Unsubscribe:
    return Unsubscribe(container.notifications_uow_factory, container.token_service)


# ── аутентификация пользователя (JWT) ────────────────────────────────────────
def _extract_access_token(request: Request) -> str | None:
    cookie = request.cookies.get(ACCESS_COOKIE_NAME)
    if cookie:
        return cookie
    scheme, param = get_authorization_scheme_param(request.headers.get("Authorization", ""))
    if scheme.lower() == "bearer" and param:
        return param
    return None


async def get_current_user(request: Request, container: ContainerDep) -> User:
    token = _extract_access_token(request)
    if not token:
        raise ApiError(HTTP_401_UNAUTHORIZED, "not_authenticated", "Требуется вход")
    try:
        claims = container.token_service.decode(token)
    except jwt.ExpiredSignatureError as exc:
        raise ApiError(HTTP_401_UNAUTHORIZED, "token_expired", "Токен истёк") from exc
    except jwt.InvalidTokenError as exc:
        raise ApiError(HTTP_401_UNAUTHORIZED, "invalid_token", "Невалидный токен") from exc

    if claims.get("type") != "access":
        raise ApiError(HTTP_401_UNAUTHORIZED, "invalid_token", "Ожидался access-токен")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.isdigit():
        raise ApiError(HTTP_401_UNAUTHORIZED, "invalid_token", "Некорректный subject")

    async with container.uow_factory() as uow:
        user = await uow.users.get_by_id(int(subject))
    if user is None or not user.is_active:
        raise ApiError(HTTP_401_UNAUTHORIZED, "user_inactive", "Пользователь недоступен")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


# ── внутренний API-key (bot↔api, worker↔api) ─────────────────────────────────
async def require_internal_api_key(
    container: ContainerDep,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    secret = container.settings.api_shared_secret
    if not secret:
        return  # open-mode (только dev): секрет не задан
    if not x_api_key or not hmac.compare_digest(x_api_key, secret):
        raise ApiError(HTTP_403_FORBIDDEN, "forbidden", "Неверный внутренний API-key")
