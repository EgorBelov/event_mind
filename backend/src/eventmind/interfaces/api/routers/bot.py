"""Bot-facing внутренний API (`/api/v1/bot/*`), защищён внутренним API-key.

Telegram-бот — вторичный клиент: он ходит в API по HTTP и НЕ имеет
пользовательского JWT. Персональные операции (лента, feedback) он делает
от имени привязанного аккаунта: сюда передаётся `chat_id`, бэкенд резолвит
его в `user_id` (через verified+enabled telegram-канал) и запускает те же
use-case'ы, что и веб. Доступ — только по `X-API-Key` (bot↔api).

Бот — самостоятельный интерфейс (B1–B5): `POST /register` создаёт аккаунт
прямо из Telegram (без email; при последующей привязке веб-аккаунта он
сливается в него), дальше — профиль «о себе», настройки, сохранённое и
«📖 Подробнее» с причинами рекомендации.

Привязка веб-аккаунта (`/start <token>`) идёт через
`POST /api/v1/channels/telegram/confirm` — здесь не дублируется.
NL-поиск и карточка события публичны — бот зовёт `/api/v1/events/*` напрямую.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from starlette.status import HTTP_404_NOT_FOUND, HTTP_409_CONFLICT

from eventmind.application.accounts.use_cases import (
    RegisterViaTelegram,
    ResolveAccountByTelegram,
    UpdatePreferences,
    UpdateProfile,
)
from eventmind.application.recommender.explain import ExplainEvent
from eventmind.application.recommender.profile import GetUserProfile, UpdateUserProfile
from eventmind.application.recommender.use_cases import (
    GetRecommendations,
    ListSavedEvents,
    RecordInteraction,
    RemoveSavedEvent,
    recommendation_cache_key,
)
from eventmind.interfaces.api.dependencies import (
    ContainerDep,
    get_explain_event_uc,
    get_list_saved_uc,
    get_recommendations_uc,
    get_record_interaction_uc,
    get_register_via_telegram,
    get_remove_saved_uc,
    get_resolve_telegram,
    get_update_preferences,
    get_update_profile,
    get_update_user_profile,
    get_user_profile_uc,
    require_internal_api_key,
)
from eventmind.interfaces.api.errors import ApiError
from eventmind.interfaces.api.schemas import (
    BotInteractionRequest,
    BotProfileRequest,
    BotRegisterRequest,
    BotRegisterResponse,
    BotSettingsResponse,
    BotSettingsUpdateRequest,
    BotStatusResponse,
    EventDetailResponse,
    ExplainResponse,
    MessageResponse,
    RecommendationResponse,
    SavedPageResponse,
    UserProfileResponse,
)

ChatId = Annotated[str, Query(min_length=1, max_length=64)]

router = APIRouter(
    prefix="/api/v1/bot",
    tags=["bot"],
    dependencies=[Depends(require_internal_api_key)],
)


async def _require_account(resolve: ResolveAccountByTelegram, chat_id: str) -> int:
    user_id = await resolve.execute(chat_id)
    if user_id is None:
        raise ApiError(
            HTTP_409_CONFLICT,
            "not_linked",
            "Этот Telegram не привязан к аккаунту EventMind",
        )
    return user_id


@router.get("/status", response_model=BotStatusResponse)
async def status(
    chat_id: ChatId,
    resolve: Annotated[ResolveAccountByTelegram, Depends(get_resolve_telegram)],
) -> BotStatusResponse:
    user_id = await resolve.execute(chat_id)
    return BotStatusResponse(linked=user_id is not None, user_id=user_id)


@router.get("/recommendations", response_model=list[RecommendationResponse])
async def recommendations(
    chat_id: ChatId,
    resolve: Annotated[ResolveAccountByTelegram, Depends(get_resolve_telegram)],
    use_case: Annotated[GetRecommendations, Depends(get_recommendations_uc)],
) -> list[RecommendationResponse]:
    user_id = await _require_account(resolve, chat_id)
    items = await use_case.execute(user_id)
    return [RecommendationResponse(**asdict(it)) for it in items]


@router.post("/interactions", response_model=MessageResponse)
async def interactions(
    payload: BotInteractionRequest,
    resolve: Annotated[ResolveAccountByTelegram, Depends(get_resolve_telegram)],
    use_case: Annotated[RecordInteraction, Depends(get_record_interaction_uc)],
) -> MessageResponse:
    user_id = await _require_account(resolve, payload.chat_id)
    await use_case.execute(user_id, payload.event_id, payload.action)
    return MessageResponse(detail="Учтено")


# ── B1: регистрация прямо в боте ──────────────────────────────────────────────
@router.post("/register", response_model=BotRegisterResponse)
async def register(
    payload: BotRegisterRequest,
    use_case: Annotated[RegisterViaTelegram, Depends(get_register_via_telegram)],
) -> BotRegisterResponse:
    """Идемпотентно по chat_id: повторный вызов вернёт существующий аккаунт."""
    result = await use_case.execute(payload.chat_id)
    return BotRegisterResponse(user_id=result.user_id, created=result.created)


# ── B2: профиль «о себе», настройки ───────────────────────────────────────────
@router.get("/profile", response_model=UserProfileResponse)
async def get_profile(
    chat_id: ChatId,
    resolve: Annotated[ResolveAccountByTelegram, Depends(get_resolve_telegram)],
    use_case: Annotated[GetUserProfile, Depends(get_user_profile_uc)],
) -> UserProfileResponse:
    user_id = await _require_account(resolve, chat_id)
    return UserProfileResponse.from_entity(await use_case.execute(user_id))


@router.put("/profile", response_model=UserProfileResponse)
async def put_profile(
    payload: BotProfileRequest,
    resolve: Annotated[ResolveAccountByTelegram, Depends(get_resolve_telegram)],
    use_case: Annotated[UpdateUserProfile, Depends(get_update_user_profile)],
) -> UserProfileResponse:
    user_id = await _require_account(resolve, payload.chat_id)
    profile = await use_case.execute(
        user_id,
        about=payload.about,
        interests=payload.interests,
        anti_interests=payload.anti_interests,
    )
    return UserProfileResponse.from_entity(profile)


async def _settings(container: ContainerDep, user_id: int) -> BotSettingsResponse:
    async with container.uow_factory() as uow:
        user = await uow.users.get_by_id(user_id)
        pref = await uow.preferences.get_by_user(user_id)
    if user is None or pref is None:
        raise ApiError(HTTP_404_NOT_FOUND, "not_found", "Настройки не найдены")
    return BotSettingsResponse(
        city=user.city,
        preferred_format=user.preferred_format,
        digest_frequency=pref.digest_frequency.value,
        quiet_hours_start=pref.quiet_hours_start,
        quiet_hours_end=pref.quiet_hours_end,
    )


@router.get("/settings", response_model=BotSettingsResponse)
async def get_settings(
    chat_id: ChatId,
    container: ContainerDep,
    resolve: Annotated[ResolveAccountByTelegram, Depends(get_resolve_telegram)],
) -> BotSettingsResponse:
    return await _settings(container, await _require_account(resolve, chat_id))


@router.patch("/settings", response_model=BotSettingsResponse)
async def patch_settings(
    payload: BotSettingsUpdateRequest,
    container: ContainerDep,
    resolve: Annotated[ResolveAccountByTelegram, Depends(get_resolve_telegram)],
    update_profile: Annotated[UpdateProfile, Depends(get_update_profile)],
    update_prefs: Annotated[UpdatePreferences, Depends(get_update_preferences)],
) -> BotSettingsResponse:
    user_id = await _require_account(resolve, payload.chat_id)
    if payload.city is not None or payload.preferred_format is not None:
        await update_profile.execute(
            user_id, city=payload.city, preferred_format=payload.preferred_format
        )
        # город/формат входят в rule-скоринг — выдачу пересчитать
        await container.cache.delete(recommendation_cache_key(user_id))
    await update_prefs.execute(
        user_id,
        digest_frequency=payload.digest_frequency,
        quiet_hours_start=payload.quiet_hours_start,
        quiet_hours_end=payload.quiet_hours_end,
        clear_quiet_hours=payload.clear_quiet_hours,
    )
    return await _settings(container, user_id)


# ── B2: сохранённое ───────────────────────────────────────────────────────────
@router.get("/saved", response_model=SavedPageResponse)
async def saved(
    chat_id: ChatId,
    resolve: Annotated[ResolveAccountByTelegram, Depends(get_resolve_telegram)],
    use_case: Annotated[ListSavedEvents, Depends(get_list_saved_uc)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> SavedPageResponse:
    user_id = await _require_account(resolve, chat_id)
    page = await use_case.execute(user_id, offset=offset, limit=limit)
    return SavedPageResponse(
        items=[EventDetailResponse.from_entity(e) for e in page.items],
        total=page.total,
        offset=page.offset,
    )


@router.delete("/saved/{event_id}", response_model=MessageResponse)
async def remove_saved(
    event_id: int,
    chat_id: ChatId,
    resolve: Annotated[ResolveAccountByTelegram, Depends(get_resolve_telegram)],
    use_case: Annotated[RemoveSavedEvent, Depends(get_remove_saved_uc)],
) -> MessageResponse:
    user_id = await _require_account(resolve, chat_id)
    if not await use_case.execute(user_id, event_id):
        raise ApiError(HTTP_404_NOT_FOUND, "not_found", "Событие не в сохранённом")
    return MessageResponse(detail="Убрано из сохранённого")


# ── B3: «📖 Подробнее» ────────────────────────────────────────────────────────
@router.get("/events/{event_id}/explain", response_model=ExplainResponse)
async def explain(
    event_id: int,
    chat_id: ChatId,
    resolve: Annotated[ResolveAccountByTelegram, Depends(get_resolve_telegram)],
    use_case: Annotated[ExplainEvent, Depends(get_explain_event_uc)],
) -> ExplainResponse:
    # причины — только для привязанного аккаунта; пересказ доступен всем
    user_id = await resolve.execute(chat_id)
    result = await use_case.execute(event_id, user_id=user_id)
    if result is None:
        raise ApiError(HTTP_404_NOT_FOUND, "not_found", "Событие не найдено")
    return ExplainResponse(
        event=EventDetailResponse.from_entity(result.event),
        summary=result.summary,
        summary_source=result.summary_source,
        reasons=result.reasons,
    )
