"""P1 №18: навыки, которых не хватает для целей (user_profiles.skill_gaps)

Revision ID: 0012_user_profiles_skill_gaps
Revises: 0011_raw_events_duplicate_of
Create Date: 2026-10-27
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_user_profiles_skill_gaps"
down_revision: str | None = "0011_raw_events_duplicate_of"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("skill_gaps", postgresql.JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "skill_gaps")
