"""Pydantic-схема нормализованного события (для LLMGateway.structured_output)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class NormalizedEvent(BaseModel):
    """Структура, которую LLM извлекает из сырого события.

    Значения по умолчанию делают схему устойчивой к частичному ответу модели;
    финальную канонизацию/валидацию делает пост-обработка нормализатора.
    """

    title: str = ""
    description: str = ""
    format: str = "unknown"
    city: str = "unknown"
    level: str = "unknown"
    date: str = Field(default="", description="Дата начала строго YYYY-MM-DD или пусто")
    topics: list[str] = Field(default_factory=list)
    event_type: str = "unknown"
    target_audience: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    seniority: str = "any"
    quality_score: int | None = None
    hype_score: int | None = None
