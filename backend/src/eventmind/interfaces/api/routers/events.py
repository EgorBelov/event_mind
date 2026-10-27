"""Роутер событий (публичный): NL-поиск + карточка события."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from starlette.status import HTTP_404_NOT_FOUND

from eventmind.application.recommender.explain import ExplainEvent
from eventmind.application.search.use_cases import GetEvent, NlSearch, SimilarEvents
from eventmind.domain.events.entities import Event
from eventmind.interfaces.api.dependencies import (
    CurrentUser,
    get_event_uc,
    get_explain_event_uc,
    get_nl_search,
    get_similar_events_uc,
)
from eventmind.interfaces.api.errors import ApiError
from eventmind.interfaces.api.schemas import EventDetailResponse, ExplainResponse, NlSearchResponse

router = APIRouter(prefix="/api/v1/events", tags=["events"])


def _to_response(event: Event) -> EventDetailResponse:
    return EventDetailResponse.from_entity(event)


@router.get("/nl-search", response_model=NlSearchResponse)
async def nl_search(
    q: Annotated[str, Query(min_length=1, max_length=500)],
    use_case: Annotated[NlSearch, Depends(get_nl_search)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> NlSearchResponse:
    result = await use_case.execute(q, limit=limit)
    return NlSearchResponse(
        relaxed=result.relaxed,
        filters=result.filters,
        results=[_to_response(e) for e in result.results],
    )


@router.get("/{event_id}", response_model=EventDetailResponse)
async def event_detail(
    event_id: int,
    use_case: Annotated[GetEvent, Depends(get_event_uc)],
) -> EventDetailResponse:
    event = await use_case.execute(event_id)
    if event is None:
        raise ApiError(HTTP_404_NOT_FOUND, "not_found", "Событие не найдено")
    return _to_response(event)


@router.get("/{event_id}/similar", response_model=list[EventDetailResponse])
async def similar_events(
    event_id: int,
    use_case: Annotated[SimilarEvents, Depends(get_similar_events_uc)],
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
) -> list[EventDetailResponse]:
    """«🔍 Похожие»: ближайшие по смыслу предстоящие события (публично)."""
    found = await use_case.execute(event_id, limit=limit)
    if found is None:
        raise ApiError(HTTP_404_NOT_FOUND, "not_found", "Событие не найдено")
    return [_to_response(e) for e in found]


@router.get("/{event_id}/explain", response_model=ExplainResponse)
async def explain_event(
    event_id: int,
    current_user: CurrentUser,
    use_case: Annotated[ExplainEvent, Depends(get_explain_event_uc)],
) -> ExplainResponse:
    """«📖 Подробнее»: пересказ события (LLM, кэш 6 ч) + почему рекомендовано."""
    result = await use_case.execute(event_id, user_id=current_user.id)
    if result is None:
        raise ApiError(HTTP_404_NOT_FOUND, "not_found", "Событие не найдено")
    return ExplainResponse.from_explanation(result)
