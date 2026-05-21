"""add user_skill_profiles table

Revision ID: d6e7f8901234
Revises: c5d6e7f89012
Create Date: 2026-05-21 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "d6e7f8901234"
down_revision = "c5d6e7f89012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_skill_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True, index=True),
        sa.Column("current_role", sa.String(), nullable=True),
        sa.Column("target_role", sa.String(), nullable=True),
        sa.Column("seniority", sa.String(), nullable=True),
        sa.Column("learning_horizon", sa.String(), nullable=True),
        sa.Column("current_skills", sa.Text(), nullable=True),
        sa.Column("target_skills", sa.Text(), nullable=True),
        sa.Column("goals", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_skill_profiles")
