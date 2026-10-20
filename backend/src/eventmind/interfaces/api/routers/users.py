"""Роутер профиля и настроек уведомлений текущего пользователя (JWT).

Профиль (город/формат) влияет на rule-скоринг рекомендера; текстовый профиль
«о себе» (`/me/profile`) — модель пользователя: LLM-выжимка + эмбеддинг,
персональная выдача до первого лайка; настройки уведомлений — на
дайджест-рассылку (частота, каналы, тихие часы).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.status import HTTP_404_NOT_FOUND

from eventmind.application.accounts.use_cases import (
    UpdatePreferences,
    UpdateProfile,
)
from eventmind.application.recommender.profile import GetUserProfile, UpdateUserProfile
from eventmind.domain.accounts.errors import UserNotFound
from eventmind.interfaces.api.dependencies import (
    ContainerDep,
    CurrentUser,
    get_update_preferences,
    get_update_profile,
    get_update_user_profile,
    get_user_profile_uc,
)
from eventmind.interfaces.api.errors import ApiError
from eventmind.interfaces.api.schemas import (
    PreferencesResponse,
    PreferencesUpdateRequest,
    ProfileUpdateRequest,
    UserProfileRequest,
    UserProfileResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser) -> UserResponse:
    return UserResponse.from_entity(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    payload: ProfileUpdateRequest,
    current_user: CurrentUser,
    use_case: Annotated[UpdateProfile, Depends(get_update_profile)],
) -> UserResponse:
    assert current_user.id is not None
    try:
        user = await use_case.execute(
            current_user.id,
            city=payload.city,
            preferred_format=payload.preferred_format,
        )
    except UserNotFound as exc:
        raise ApiError(HTTP_404_NOT_FOUND, "not_found", "Пользователь не найден") from exc
    return UserResponse.from_entity(user)


@router.get("/me/profile", response_model=UserProfileResponse)
async def get_user_profile(
    current_user: CurrentUser,
    use_case: Annotated[GetUserProfile, Depends(get_user_profile_uc)],
) -> UserProfileResponse:
    assert current_user.id is not None
    return UserProfileResponse.from_entity(await use_case.execute(current_user.id))


@router.put("/me/profile", response_model=UserProfileResponse)
async def put_user_profile(
    payload: UserProfileRequest,
    current_user: CurrentUser,
    use_case: Annotated[UpdateUserProfile, Depends(get_update_user_profile)],
) -> UserProfileResponse:
    assert current_user.id is not None
    profile = await use_case.execute(
        current_user.id,
        about=payload.about,
        interests=payload.interests,
        anti_interests=payload.anti_interests,
    )
    return UserProfileResponse.from_entity(profile)


@router.get("/me/preferences", response_model=PreferencesResponse)
async def get_preferences(
    current_user: CurrentUser,
    container: ContainerDep,
) -> PreferencesResponse:
    assert current_user.id is not None
    async with container.uow_factory() as uow:
        pref = await uow.preferences.get_by_user(current_user.id)
    if pref is None:
        raise ApiError(HTTP_404_NOT_FOUND, "not_found", "Настройки не найдены")
    return PreferencesResponse.from_entity(pref)


@router.patch("/me/preferences", response_model=PreferencesResponse)
async def update_preferences(
    payload: PreferencesUpdateRequest,
    current_user: CurrentUser,
    use_case: Annotated[UpdatePreferences, Depends(get_update_preferences)],
) -> PreferencesResponse:
    assert current_user.id is not None
    try:
        pref = await use_case.execute(
            current_user.id,
            digest_frequency=payload.digest_frequency,
            email_enabled=payload.email_enabled,
            telegram_enabled=payload.telegram_enabled,
            quiet_hours_start=payload.quiet_hours_start,
            quiet_hours_end=payload.quiet_hours_end,
        )
    except UserNotFound as exc:
        raise ApiError(HTTP_404_NOT_FOUND, "not_found", "Настройки не найдены") from exc
    return PreferencesResponse.from_entity(pref)
