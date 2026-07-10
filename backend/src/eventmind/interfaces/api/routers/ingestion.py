"""Роутер ingestion (внутренний API-key): загрузка источников и нормализация.

- `POST /api/v1/ingestion/load/{source}` — один источник в raw_events.
- `POST /api/v1/ingestion/load-all`      — все источники по очереди.
- `POST /api/v1/ingestion/normalize`     — нормализовать пачку raw → events.
- `POST /api/v1/ingestion/retry-failed`  — переобработать failed (в пределах ретраев).
- `GET  /api/v1/ingestion/status`        — счётчики по статусам raw_events + events.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from eventmind.application.ingestion.use_cases import (
    GetIngestionStatus,
    LoadAllSources,
    LoadSource,
    NormalizeRawEvents,
)
from eventmind.domain.events.value_objects import RawEventStatus
from eventmind.interfaces.api.dependencies import (
    ContainerDep,
    get_ingestion_status,
    get_load_all,
    get_load_source,
    get_normalize_raw_events,
    require_internal_api_key,
)
from eventmind.interfaces.api.errors import ApiError

router = APIRouter(
    prefix="/api/v1/ingestion",
    tags=["ingestion"],
    dependencies=[Depends(require_internal_api_key)],
)


@router.post("/load/{source}")
async def load_source(
    source: str,
    container: ContainerDep,
    use_case: Annotated[LoadSource, Depends(get_load_source)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    event_source = container.sources.get(source)
    if event_source is None:
        raise ApiError(404, "unknown_source", f"Источник {source!r} не зарегистрирован")
    return asdict(await use_case.execute(event_source, limit=limit))


@router.post("/load-all")
async def load_all(
    use_case: Annotated[LoadAllSources, Depends(get_load_all)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    results = await use_case.execute(limit=limit)
    return {"sources": [asdict(r) for r in results]}


@router.post("/normalize")
async def normalize(
    use_case: Annotated[NormalizeRawEvents, Depends(get_normalize_raw_events)],
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
) -> dict[str, Any]:
    return asdict(await use_case.execute(limit=limit))


@router.post("/retry-failed")
async def retry_failed(
    use_case: Annotated[NormalizeRawEvents, Depends(get_normalize_raw_events)],
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
) -> dict[str, Any]:
    return asdict(
        await use_case.execute(limit=limit, statuses=[RawEventStatus.FAILED])
    )


@router.get("/status")
async def status(
    use_case: Annotated[GetIngestionStatus, Depends(get_ingestion_status)],
) -> dict[str, Any]:
    return await use_case.execute()
