from pydantic import BaseModel


class EventResponse(BaseModel):
    id: int
    title: str
    description: str
    format: str
    city: str
    level: str
    date: str
    topics: list[str]

    class Config:
        from_attributes = True