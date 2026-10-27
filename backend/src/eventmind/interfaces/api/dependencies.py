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
from starlette.status import (
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from eventmind.application.accounts.use_cases import (
    AuthenticateUser,
    AuthenticateWithGoogle,
    ConfirmTelegramLink,
    CreateTelegramLinkToken,
    RegisterUser,
    RegisterViaTelegram,
    RequestPasswordReset,
    ResetPassword,
    ResolveAccountByTelegram,
    UpdatePreferences,
    UpdateProfile,
    VerifyEmail,
)
from eventmind.application.agent.session import AgentSessionStore
from eventmind.application.agent.tools import (
    AgentToolbox,
    ExplainEventTool,
    GetEventTool,
    GetProfileTool,
    RecommendTool,
    RecordFeedbackTool,
    SearchEventsTool,
    UpdateProfileTool,
    UpdateSettingsTool,
)
from eventmind.application.agent.use_cases import (
    AgentTurn,
    ConfirmAgentAction,
    GetAgentHistory,
    ResetAgentSession,
)
from eventmind.application.ingestion.dedup import DuplicateArbiter
from eventmind.application.ingestion.use_cases import (
    BackfillEventEmbeddings,
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
from eventmind.application.recommender.explain import ExplainEvent
from eventmind.application.recommender.profile import (
    ApplyProfileChanges,
    GetUserProfile,
    UpdateUserProfile,
)
from eventmind.application.recommender.use_cases import (
    GetRecommendations,
    ListSavedEvents,
    RecordInteraction,
    RefreshUserEmbeddings,
    RemoveSavedEvent,
)
from eventmind.application.search.config import SearchConfig
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


def get_resolve_telegram(container: ContainerDep) -> ResolveAccountByTelegram:
    return ResolveAccountByTelegram(container.uow_factory)


def get_register_via_telegram(container: ContainerDep) -> RegisterViaTelegram:
    return RegisterViaTelegram(container.uow_factory)


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
        DuplicateArbiter(container.llm) if container.settings.dedup_llm_arbiter else None,
    )


def get_ingestion_status(container: ContainerDep) -> GetIngestionStatus:
    return GetIngestionStatus(container.events_uow_factory)


def get_backfill_event_embeddings(container: ContainerDep) -> BackfillEventEmbeddings:
    return BackfillEventEmbeddings(
        container.events_uow_factory,
        container.embedding,
        text_mode=container.ingestion_config.embedding_text_mode,
    )


def get_refresh_user_embeddings(container: ContainerDep) -> RefreshUserEmbeddings:
    return RefreshUserEmbeddings(container.recommendation_uow_factory, container.cache)


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


def get_update_user_profile(container: ContainerDep) -> UpdateUserProfile:
    return UpdateUserProfile(
        container.recommendation_uow_factory,
        container.profile_extractor,
        container.embedding,
        container.cache,
        container.clock,
    )


def get_user_profile_uc(container: ContainerDep) -> GetUserProfile:
    return GetUserProfile(container.recommendation_uow_factory)


def get_list_saved_uc(container: ContainerDep) -> ListSavedEvents:
    return ListSavedEvents(container.recommendation_uow_factory)


def get_remove_saved_uc(container: ContainerDep) -> RemoveSavedEvent:
    return RemoveSavedEvent(
        container.recommendation_uow_factory, container.cache, container.clock, ScoringWeights()
    )


def get_explain_event_uc(container: ContainerDep) -> ExplainEvent:
    return ExplainEvent(
        container.search_repository,
        container.recommendation_uow_factory,
        container.llm,
        container.cache,
        container.clock,
        ScoringWeights(),
    )


def get_record_interaction_uc(container: ContainerDep) -> RecordInteraction:
    return RecordInteraction(
        container.recommendation_uow_factory, container.cache, container.clock, ScoringWeights()
    )


# ── поиск событий (M6) ───────────────────────────────────────────────────────
def get_nl_search(container: ContainerDep) -> NlSearch:
    settings = container.settings
    return NlSearch(
        container.llm,
        container.search_repository,
        container.clock,
        container.cache,
        container.embedding,
        SearchConfig(
            hybrid=settings.search_hybrid_enabled,
            hyde=settings.search_hyde_enabled,
            min_similarity=settings.search_min_similarity,
        ),
    )


def get_event_uc(container: ContainerDep) -> GetEvent:
    return GetEvent(container.search_repository)


# ── диалоговый агент (A1–A5) ─────────────────────────────────────────────────
def get_apply_profile_changes(container: ContainerDep) -> ApplyProfileChanges:
    return ApplyProfileChanges(
        container.recommendation_uow_factory,
        container.embedding,
        container.cache,
        container.clock,
    )


def _agent_toolbox(container: Container) -> AgentToolbox:
    return AgentToolbox(
        [
            SearchEventsTool(get_nl_search(container)),
            RecommendTool(get_recommendations_uc(container), container.search_repository),
            GetEventTool(container.search_repository),
            ExplainEventTool(get_explain_event_uc(container)),
            GetProfileTool(get_user_profile_uc(container), container.recommendation_uow_factory),
            RecordFeedbackTool(get_record_interaction_uc(container)),
            UpdateProfileTool(get_apply_profile_changes(container)),
            UpdateSettingsTool(get_update_profile(container), container.cache),
        ],
        allowed=container.agent_config.allowed_tools,
    )


def _agent_sessions(container: Container) -> AgentSessionStore:
    return AgentSessionStore(
        container.cache,
        ttl_seconds=container.agent_config.session_ttl_seconds,
        history_limit=container.agent_config.history_limit,
    )


def _require_agent(container: Container) -> None:
    if not container.settings.agent_enabled:
        raise ApiError(HTTP_503_SERVICE_UNAVAILABLE, "agent_disabled", "Помощник отключён")


def get_agent_turn(container: ContainerDep) -> AgentTurn:
    _require_agent(container)
    return AgentTurn(
        container.llm,
        _agent_toolbox(container),
        _agent_sessions(container),
        container.agent_journal,
        container.recommendation_uow_factory,
        container.cache,
        container.clock,
        container.agent_config,
    )


def get_confirm_agent_action(container: ContainerDep) -> ConfirmAgentAction:
    _require_agent(container)
    return ConfirmAgentAction(
        container.llm,
        _agent_toolbox(container),
        _agent_sessions(container),
        container.agent_journal,
        container.recommendation_uow_factory,
        container.cache,
        container.clock,
        container.agent_config,
    )


def get_agent_history(container: ContainerDep) -> GetAgentHistory:
    _require_agent(container)
    return GetAgentHistory(_agent_sessions(container))


def get_reset_agent(container: ContainerDep) -> ResetAgentSession:
    return ResetAgentSession(_agent_sessions(container))


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
