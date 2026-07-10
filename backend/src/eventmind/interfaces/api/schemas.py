"""Pydantic-схемы запросов/ответов API (границы транспорта)."""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from eventmind.domain.accounts.entities import NotificationPreference, User


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
    city: str | None = None
    preferred_format: str | None = None

    @classmethod
    def from_entity(cls, user: User) -> UserResponse:
        assert user.id is not None
        return cls(
            id=user.id,
            email=user.email,
            email_verified=user.email_verified,
            is_active=user.is_active,
            city=user.city,
            preferred_format=user.preferred_format,
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


class EventDetailResponse(BaseModel):
    id: int
    source: str
    title: str
    description: str
    format: str
    city: str
    level: str
    date: str
    start_at: str | None
    event_type: str | None
    target_audience: str | None
    source_url: str | None
    summary: str | None
    tech_stack: list[str]
    seniority: str | None
    quality_score: int | None
    hype_score: int | None
    series_slug: str | None
    topics: list[str]


class NlSearchResponse(BaseModel):
    relaxed: bool
    filters: dict[str, object]
    results: list[EventDetailResponse]


class ProfileUpdateRequest(BaseModel):
    city: str | None = None
    preferred_format: str | None = None


class PreferencesUpdateRequest(BaseModel):
    digest_frequency: str | None = Field(default=None, pattern="^(off|daily|weekly)$")
    email_enabled: bool | None = None
    telegram_enabled: bool | None = None
    quiet_hours_start: int | None = Field(default=None, ge=0, le=23)
    quiet_hours_end: int | None = Field(default=None, ge=0, le=23)


class GoogleAuthRequest(BaseModel):
    id_token: str = Field(min_length=1)


class BotStatusResponse(BaseModel):
    """Статус привязки Telegram chat_id к аккаунту (для bot-facing API)."""

    linked: bool
    user_id: int | None = None


class BotInteractionRequest(BaseModel):
    chat_id: str = Field(min_length=1, max_length=64)
    event_id: int
    action: str = Field(pattern="^(like|dislike|save|view)$")


class PreferencesResponse(BaseModel):
    digest_frequency: str
    email_enabled: bool
    telegram_enabled: bool
    quiet_hours_start: int | None
    quiet_hours_end: int | None

    @classmethod
    def from_entity(cls, pref: NotificationPreference) -> PreferencesResponse:
        return cls(
            digest_frequency=pref.digest_frequency.value,
            email_enabled=pref.email_enabled,
            telegram_enabled=pref.telegram_enabled,
            quiet_hours_start=pref.quiet_hours_start,
            quiet_hours_end=pref.quiet_hours_end,
        )
