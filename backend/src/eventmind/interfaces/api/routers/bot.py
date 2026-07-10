"""Bot-facing внутренний API (`/api/v1/bot/*`), защищён внутренним API-key.

Telegram-бот — вторичный клиент: он ходит в API по HTTP и НЕ имеет
пользовательского JWT. Персональные операции (лента, feedback) он делает
от имени привязанного аккаунта: сюда передаётся `chat_id`, бэкенд резолвит
его в `user_id` (через verified+enabled telegram-канал) и запускает те же
use-case'ы, что и веб. Доступ — только по `X-API-Key` (bot↔api).

Привязка аккаунта (`/start <token>`) идёт через
`POST /api/v1/channels/telegram/confirm` — здесь не дублируется.
NL-поиск и карточка события публичны — бот зовёт `/api/v1/events/*` напрямую.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from starlette.status import HTTP_409_CONFLICT

from eventmind.application.accounts.use_cases import ResolveAccountByTelegram
from eventmind.application.recommender.use_cases import (
    GetRecommendations,
    RecordInteraction,
)
from eventmind.interfaces.api.dependencies import (
    get_recommendations_uc,
    get_record_interaction_uc,
    get_resolve_telegram,
    require_internal_api_key,
)
from eventmind.interfaces.api.errors import ApiError
from eventmind.interfaces.api.schemas import (
    BotInteractionRequest,
    BotStatusResponse,
    MessageResponse,
    RecommendationResponse,
)

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
    chat_id: Annotated[str, Query(min_length=1, max_length=64)],
    resolve: Annotated[ResolveAccountByTelegram, Depends(get_resolve_telegram)],
) -> BotStatusResponse:
    user_id = await resolve.execute(chat_id)
    return BotStatusResponse(linked=user_id is not None, user_id=user_id)


@router.get("/recommendations", response_model=list[RecommendationResponse])
async def recommendations(
    chat_id: Annotated[str, Query(min_length=1, max_length=64)],
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
