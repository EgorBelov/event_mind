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
    score: int
    explanation: str


class InteractionCreate(BaseModel):
    telegram_id: int
    event_id: int
    action: str