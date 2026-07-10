"""M3: схема ingestion (topics, events+vector+HNSW, event_topics, raw_events)

Revision ID: 0003_ingestion
Revises: 0002_accounts
Create Date: 2026-07-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0003_ingestion"
down_revision: str | None = "0002_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 384


def upgrade() -> None:
    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_topics_code", "topics", ["code"], unique=True)

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("city", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=32), nullable=False),
        sa.Column("date", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=True),
        sa.Column("target_audience", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("tech_stack", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("seniority", sa.String(length=16), nullable=True),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("hype_score", sa.Integer(), nullable=True),
        sa.Column("series_slug", sa.String(length=120), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_url", name="uq_events_source_url"),
    )
    op.create_index("ix_events_source", "events", ["source"])
    op.create_index("ix_events_city", "events", ["city"])
    op.create_index("ix_events_start_at", "events", ["start_at"])
    op.create_index("ix_events_series_slug", "events", ["series_slug"])
    op.execute(
        "CREATE INDEX ix_events_embedding_hnsw ON events "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "event_topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", "topic_id", name="uq_event_topic"),
    )
    op.create_index("ix_event_topics_event_id", "event_topics", ["event_id"])
    op.create_index("ix_event_topics_topic_id", "event_topics", ["topic_id"])

    op.create_table(
        "raw_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("raw_description", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="raw"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "source_url", name="uq_raw_event_source_url"),
    )
    op.create_index("ix_raw_events_source", "raw_events", ["source"])
    op.create_index("ix_raw_events_status", "raw_events", ["status"])


def downgrade() -> None:
    op.drop_table("raw_events")
    op.drop_index("ix_event_topics_topic_id", table_name="event_topics")
    op.drop_index("ix_event_topics_event_id", table_name="event_topics")
    op.drop_table("event_topics")
    op.execute("DROP INDEX IF EXISTS ix_events_embedding_hnsw")
    op.drop_table("events")
    op.drop_index("ix_topics_code", table_name="topics")
    op.drop_table("topics")
