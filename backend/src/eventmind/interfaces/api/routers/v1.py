"""Корень версии API `/api/v1`.

В M0 — заглушка с метаинформацией. Начиная с M1 сюда монтируются
роутеры доменных фич (auth, channels, recommendations, search, ...).
"""
from __future__ import annotations

from fastapi import APIRouter

from eventmind import __version__

router = APIRouter(prefix="/api/v1")


@router.get("/", summary="Версия и статус API v1")
async def api_root() -> dict[str, str]:
    return {"service": "eventmind", "api": "v1", "version": __version__}
