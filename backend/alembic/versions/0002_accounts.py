"""M1: account-центричная схема (users, channels, preferences, tokens, outbox)

Единая консистентная миграция аккаунтов с день-1 индексами под hot-path и
HNSW-индексом на pgvector-колонке `users.embedding`. Таблицы событий/
рекомендаций добавятся в своих milestone'ах (M3/M4).

Revision ID: 0002_accounts
Revises: 0001_initial_pgvector
Create Date: 2026-07-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002_accounts"
down_revision: str | None = "0001_initial_pgvector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 384


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("oauth_provider", sa.String(length=32), nullable=True),
        sa.Column("oauth_sub", sa.String(length=255), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    # HNSW-индекс для kNN по эмбеддингу (cosine). Нужен рекомендеру (M4);
    # заводим сразу, чтобы схема была консистентной с день-1.
    op.execute(
        "CREATE INDEX ix_users_embedding_hnsw ON users "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "user_channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("address", sa.String(length=320), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "type", name="uq_user_channel_user_type"),
        sa.UniqueConstraint("type", "address", name="uq_user_channel_type_address"),
    )
    op.create_index("ix_user_channels_user_id", "user_channels", ["user_id"])

    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("digest_frequency", sa.String(length=16), nullable=False, server_default="daily"),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("telegram_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("quiet_hours_start", sa.Integer(), nullable=True),
        sa.Column("quiet_hours_end", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_notification_pref_user"),
    )
    op.create_index(
        "ix_notification_preferences_user_id", "notification_preferences", ["user_id"]
    )

    op.create_table(
        "one_time_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("purpose", "token_hash", name="uq_one_time_token_purpose_hash"),
    )
    op.create_index("ix_one_time_tokens_user_id", "one_time_tokens", ["user_id"])

    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Частичный индекс под hot-path релея: выбираем только pending.
    op.execute(
        "CREATE INDEX ix_outbox_pending ON outbox (id) WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.drop_table("outbox")
    op.drop_index("ix_one_time_tokens_user_id", table_name="one_time_tokens")
    op.drop_table("one_time_tokens")
    op.drop_index("ix_notification_preferences_user_id", table_name="notification_preferences")
    op.drop_table("notification_preferences")
    op.drop_index("ix_user_channels_user_id", table_name="user_channels")
    op.drop_table("user_channels")
    op.execute("DROP INDEX IF EXISTS ix_users_embedding_hnsw")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
