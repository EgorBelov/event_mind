"""Админ-роутер: интроспекция и управление LLM-цепочкой (внутренний API-key).

- `GET  /api/v1/admin/llm/status`  — состояние breaker'а и звеньев цепочки.
- `POST /api/v1/admin/llm/reprobe` — пере-пробить рабочую Gemini-модель
  (free-tier меняет квоты моделей без предупреждения) и пересобрать звенья.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from eventmind.infrastructure.llm.providers import reprobe_chain
from eventmind.interfaces.api.dependencies import ContainerDep, require_internal_api_key

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_internal_api_key)],
)


@router.get("/llm/status")
async def llm_status(container: ContainerDep) -> dict[str, Any]:
    return container.llm.status()


@router.post("/llm/reprobe")
async def llm_reprobe(container: ContainerDep) -> dict[str, Any]:
    model = await reprobe_chain(container.llm, container.settings)
    return {"selected_gemini_model": model, "status": container.llm.status()}
