from pydantic import BaseModel


class UserCreate(BaseModel):
    telegram_id: int
    username: str | None = None
    preferred_format: str | None = None
    city: str | None = None
    topics: list[str] = []


class UserResponse(BaseModel):
    id: int
    telegram_id: int
    username: str | None = None
    preferred_format: str | None = None
    city: str | None = None
    topics: list[str]

    class Config:
        from_attributes = True