"""Роутер рекомендаций (JWT): read-only выдача + feedback (online-обучение).

- `GET  /api/v1/recommendations` — персональная лента (read-only, из кэша).
- `POST /api/v1/interactions`     — like/dislike/save/view: учит модель и
  инвалидирует кэш выдачи пользователя.
- `GET  /api/v1/saved`            — «Сохранённое» (общее с ботом), пагинация.
- `DELETE /api/v1/saved/{id}`     — убрать из сохранённого (откат сигнала).
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from starlette.status import HTTP_404_NOT_FOUND

from eventmind.application.recommender.use_cases import (
    GetRecommendations,
    ListSavedEvents,
    RecordInteraction,
    RemoveSavedEvent,
)
from eventmind.interfaces.api.dependencies import (
    CurrentUser,
    get_list_saved_uc,
    get_recommendations_uc,
    get_record_interaction_uc,
    get_remove_saved_uc,
)
from eventmind.interfaces.api.errors import ApiError
from eventmind.interfaces.api.schemas import (
    EventDetailResponse,
    InteractionRequest,
    MessageResponse,
    RecommendationResponse,
    SavedPageResponse,
)

router = APIRouter(prefix="/api/v1", tags=["recommendations"])


@router.get("/recommendations", response_model=list[RecommendationResponse])
async def recommendations(
    current_user: CurrentUser,
    use_case: Annotated[GetRecommendations, Depends(get_recommendations_uc)],
) -> list[RecommendationResponse]:
    assert current_user.id is not None
    items = await use_case.execute(current_user.id)
    return [RecommendationResponse(**asdict(it)) for it in items]


@router.post("/interactions", response_model=MessageResponse)
async def record_interaction(
    payload: InteractionRequest,
    current_user: CurrentUser,
    use_case: Annotated[RecordInteraction, Depends(get_record_interaction_uc)],
) -> MessageResponse:
    assert current_user.id is not None
    await use_case.execute(current_user.id, payload.event_id, payload.action)
    return MessageResponse(detail="Учтено")


@router.get("/saved", response_model=SavedPageResponse)
async def list_saved(
    current_user: CurrentUser,
    use_case: Annotated[ListSavedEvents, Depends(get_list_saved_uc)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> SavedPageResponse:
    assert current_user.id is not None
    page = await use_case.execute(current_user.id, offset=offset, limit=limit)
    return SavedPageResponse(
        items=[EventDetailResponse.from_entity(e) for e in page.items],
        total=page.total,
        offset=page.offset,
    )


@router.delete("/saved/{event_id}", response_model=MessageResponse)
async def remove_saved(
    event_id: int,
    current_user: CurrentUser,
    use_case: Annotated[RemoveSavedEvent, Depends(get_remove_saved_uc)],
) -> MessageResponse:
    assert current_user.id is not None
    if not await use_case.execute(current_user.id, event_id):
        raise ApiError(HTTP_404_NOT_FOUND, "not_found", "Событие не в сохранённом")
    return MessageResponse(detail="Убрано из сохранённого")
