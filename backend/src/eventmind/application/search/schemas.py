"""Схема извлекаемых NL-фильтров (для LLMGateway.structured_output)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SearchFilters(BaseModel):
    """Фильтры, извлекаемые LLM из фразы обычного языка."""

    date_from: str | None = Field(
        default=None,
        description="Начало диапазона YYYY-MM-DD (== date_to для точной даты); null если нет",
    )
    date_to: str | None = Field(
        default=None, description="Дата конца диапазона YYYY-MM-DD; null если дат нет"
    )
    city: str | None = Field(default=None, description="Город (slug/название) или null")
    event_type: str | None = Field(
        default=None, description="meetup/conference/webinar/workshop/hackathon/lecture или null"
    )
    format: str | None = Field(default=None, description="online/offline/hybrid или null")
    topics: list[str] = Field(default_factory=list, description="slug'и тем")
    free_text: str = Field(default="", description="Остаток запроса без дат/города/типа/формата")
