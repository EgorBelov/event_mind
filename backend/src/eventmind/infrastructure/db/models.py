"""ORM-модели (адаптеры таблиц) v2. Наследуют общий `Base`.

Домен (`domain/accounts`) остаётся чистым — эти модели живут только в
`infrastructure`, маппинг доменные↔ORM делают репозитории. pgvector-колонка
`users.embedding` заводится с день-1 (HNSW-индекс создаёт миграция).
"""
from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eventmind.infrastructure.db.base import Base

EMBEDDING_DIM = 384


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Задел под соц-логин (Google) — включается в M6.
    oauth_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    oauth_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # pgvector: эмбеддинг интересов пользователя (HNSW-индекс — в миграции).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UserChannelModel(Base):
    __tablename__ = "user_channels"
    __table_args__ = (
        UniqueConstraint("user_id", "type", name="uq_user_channel_user_type"),
        UniqueConstraint("type", "address", name="uq_user_channel_type_address"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    # telegram chat_id хранится строкой; BIGINT-семантика — на стороне бота.
    address: Mapped[str] = mapped_column(String(320), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NotificationPreferenceModel(Base):
    __tablename__ = "notification_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    digest_frequency: Mapped[str] = mapped_column(String(16), nullable=False, default="daily")
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quiet_hours_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quiet_hours_end: Mapped[int | None] = mapped_column(Integer, nullable=True)


class OneTimeTokenModel(Base):
    __tablename__ = "one_time_tokens"
    __table_args__ = (
        UniqueConstraint("purpose", "token_hash", name="uq_one_time_token_purpose_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OutboxModel(Base):
    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
