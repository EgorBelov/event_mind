"""Pydantic-схемы запросов/ответов API (границы транспорта)."""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from eventmind.domain.accounts.entities import User


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    id: int
    email: str
    email_verified: bool
    is_active: bool

    @classmethod
    def from_entity(cls, user: User) -> UserResponse:
        assert user.id is not None
        return cls(
            id=user.id,
            email=user.email,
            email_verified=user.email_verified,
            is_active=user.is_active,
        )


class AuthResponse(BaseModel):
    """Ответ логина/регистрации: пользователь + access-токен (дублирует cookie)."""

    user: UserResponse
    access_token: str
    token_type: str = "bearer"


class MessageResponse(BaseModel):
    status: str = "ok"
    detail: str | None = None


class TelegramLinkTokenResponse(BaseModel):
    token: str
    deep_link: str


class TelegramConfirmRequest(BaseModel):
    token: str = Field(min_length=1)
    chat_id: str = Field(min_length=1, max_length=64)


class RecommendationResponse(BaseModel):
    event_id: int
    title: str
    description: str
    date: str
    city: str
    format: str
    event_type: str | None
    source_url: str | None
    score: float
    topics: list[str]


class InteractionRequest(BaseModel):
    event_id: int
    action: str = Field(pattern="^(like|dislike|save|view)$")


class NotificationResponse(BaseModel):
    id: int
    type: str
    title: str
    body: str
    payload: dict[str, object]
    read: bool


class InboxResponse(BaseModel):
    unread: int
    items: list[NotificationResponse]
