from typing import Literal

from pydantic import BaseModel


class RecommendationResponse(BaseModel):
    event_id: int
    title: str
    description: str
    format: str
    city: str
    level: str
    date: str
    topics: list[str]
    score: float
    explanation: str
    summary: str | None = None
    source_url: str | None = None


class InteractionCreate(BaseModel):
    telegram_id: int
    event_id: int
    action: Literal["like", "dislike", "save"]
