"""Роутер рекомендаций (JWT): read-only выдача + feedback (online-обучение).

- `GET  /api/v1/recommendations` — персональная лента (read-only, из кэша).
- `POST /api/v1/interactions`     — like/dislike/save/view: учит модель и
  инвалидирует кэш выдачи пользователя.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends

from eventmind.application.recommender.use_cases import (
    GetRecommendations,
    RecordInteraction,
)
from eventmind.interfaces.api.dependencies import (
    CurrentUser,
    get_recommendations_uc,
    get_record_interaction_uc,
)
from eventmind.interfaces.api.schemas import (
    InteractionRequest,
    MessageResponse,
    RecommendationResponse,
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
