"""Pydantic-схемы запросов/ответов API (границы транспорта)."""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from eventmind.application.agent.session import PendingAction
from eventmind.application.agent.use_cases import AgentReply
from eventmind.domain.accounts.entities import NotificationPreference, User
from eventmind.domain.events.entities import Event
from eventmind.domain.recommender.user_model import UserProfile


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
    email: str | None  # None — аккаунт создан в Telegram-боте
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

    @classmethod
    def from_entity(cls, event: Event) -> EventDetailResponse:
        assert event.id is not None
        return cls(
            id=event.id,
            source=event.source,
            title=event.title,
            description=event.description,
            format=event.format,
            city=event.city,
            level=event.level,
            date=event.date,
            start_at=event.start_at.isoformat() if event.start_at else None,
            event_type=event.event_type,
            target_audience=event.target_audience,
            source_url=event.source_url,
            summary=event.summary,
            tech_stack=event.tech_stack,
            seniority=event.seniority,
            quality_score=event.quality_score,
            hype_score=event.hype_score,
            series_slug=event.series_slug,
            topics=event.topics,
        )


class SavedPageResponse(BaseModel):
    items: list[EventDetailResponse]
    total: int
    offset: int


class ExplainResponse(BaseModel):
    """«📖 Подробнее»: пересказ события + персональные причины рекомендации."""

    event: EventDetailResponse
    summary: str
    summary_source: str  # llm | description
    reasons: list[str]


class NlSearchResponse(BaseModel):
    relaxed: bool
    filters: dict[str, object]
    results: list[EventDetailResponse]


class ProfileUpdateRequest(BaseModel):
    city: str | None = None
    preferred_format: str | None = None


class UserProfileRequest(BaseModel):
    """Текст «о себе» + необязательные правки списков (перекрывают извлечённое LLM)."""

    about: str = Field(default="", max_length=4000)
    interests: list[str] | None = Field(default=None, max_length=30)
    anti_interests: list[str] | None = Field(default=None, max_length=30)


class UserProfileResponse(BaseModel):
    """Как система видит пользователя: текст + структурная выжимка."""

    about: str
    role: str
    level: str
    stack: list[str]
    interests: list[str]
    anti_interests: list[str]
    goals: list[str]
    has_embedding: bool
    is_empty: bool

    @classmethod
    def from_entity(cls, profile: UserProfile) -> UserProfileResponse:
        return cls(
            about=profile.about,
            role=profile.role,
            level=profile.level,
            stack=profile.stack,
            interests=profile.interests,
            anti_interests=profile.anti_interests,
            goals=profile.goals,
            has_embedding=profile.embedding is not None,
            is_empty=profile.is_empty,
        )


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


class BotRegisterRequest(BaseModel):
    chat_id: str = Field(min_length=1, max_length=64)


class BotRegisterResponse(BaseModel):
    user_id: int
    created: bool


class BotProfileRequest(UserProfileRequest):
    chat_id: str = Field(min_length=1, max_length=64)


class BotSettingsResponse(BaseModel):
    city: str | None
    preferred_format: str | None
    digest_frequency: str
    quiet_hours_start: int | None
    quiet_hours_end: int | None


class BotSettingsUpdateRequest(BaseModel):
    """None — поле не меняется; пустая строка city / preferred_format — «не важно»."""

    chat_id: str = Field(min_length=1, max_length=64)
    city: str | None = Field(default=None, max_length=64)
    preferred_format: str | None = Field(default=None, pattern="^(|online|offline|hybrid)$")
    digest_frequency: str | None = Field(default=None, pattern="^(off|daily|weekly)$")
    quiet_hours_start: int | None = Field(default=None, ge=0, le=23)
    quiet_hours_end: int | None = Field(default=None, ge=0, le=23)
    clear_quiet_hours: bool = False


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


# ── диалоговый агент (A4/A5) ──────────────────────────────────────────────────
class AgentMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class AgentConfirmRequest(BaseModel):
    action_id: str = Field(min_length=1, max_length=64)
    approve: bool


class BotAgentMessageRequest(AgentMessageRequest):
    chat_id: str = Field(min_length=1, max_length=64)


class BotAgentConfirmRequest(AgentConfirmRequest):
    chat_id: str = Field(min_length=1, max_length=64)


class AgentPendingResponse(BaseModel):
    """Предложенное изменение — интерфейс показывает «Да / Нет»."""

    id: str
    description: str

    @classmethod
    def from_pending(cls, pending: PendingAction | None) -> AgentPendingResponse | None:
        return cls(id=pending.id, description=pending.description) if pending else None


class AgentReplyResponse(BaseModel):
    text: str
    events: list[EventDetailResponse]
    pending: AgentPendingResponse | None
    stop_reason: str
    # true — LLM недоступна: интерфейс отвечает без агента (бот — прямым поиском)
    degraded: bool

    @classmethod
    def from_reply(cls, reply: AgentReply) -> AgentReplyResponse:
        return cls(
            text=reply.text,
            events=[EventDetailResponse.from_entity(e) for e in reply.events],
            pending=AgentPendingResponse.from_pending(reply.pending),
            stop_reason=reply.stop_reason,
            degraded=reply.degraded,
        )


class AgentHistoryMessage(BaseModel):
    role: str  # user | assistant
    text: str


class AgentHistoryResponse(BaseModel):
    messages: list[AgentHistoryMessage]
    pending: AgentPendingResponse | None
