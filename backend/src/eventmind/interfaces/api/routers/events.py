"""Роутер событий (публичный): NL-поиск + карточка события."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from starlette.status import HTTP_404_NOT_FOUND

from eventmind.application.search.use_cases import GetEvent, NlSearch
from eventmind.domain.events.entities import Event
from eventmind.interfaces.api.dependencies import get_event_uc, get_nl_search
from eventmind.interfaces.api.errors import ApiError
from eventmind.interfaces.api.schemas import EventDetailResponse, NlSearchResponse

router = APIRouter(prefix="/api/v1/events", tags=["events"])


def _to_response(event: Event) -> EventDetailResponse:
    assert event.id is not None
    return EventDetailResponse(
        id=event.id,
        source=event.source,
        title=event.title,
        description=event.description,
        format=event.format,
        city=event.city,
        level=event.level,
        date=event.date,
        start_at=event.start_at.isoformat() if event.start_at else None,
        event_type=event.event_type,
        target_audience=event.target_audience,
        source_url=event.source_url,
        summary=event.summary,
        tech_stack=event.tech_stack,
        seniority=event.seniority,
        quality_score=event.quality_score,
        hype_score=event.hype_score,
        series_slug=event.series_slug,
        topics=event.topics,
    )


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
