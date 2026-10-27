"""P1 №14: провенанс LLM-извлечения события (llm_provider, prompt_version)

Какой провайдер цепочки и какая версия промпта нормализатора извлекли поля
события — для воспроизводимости и разбора ошибок извлечения.

Revision ID: 0009_event_provenance
Revises: 0008_agent_tool_calls
Create Date: 2026-10-27
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_event_provenance"
down_revision: str | None = "0008_agent_tool_calls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("llm_provider", sa.String(length=64), nullable=True))
    op.add_column("events", sa.Column("prompt_version", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "prompt_version")
    op.drop_column("events", "llm_provider")
