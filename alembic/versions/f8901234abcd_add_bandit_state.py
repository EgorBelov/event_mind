"""add user_bandit_states

Revision ID: f8901234abcd
Revises: e7f890123456
Create Date: 2026-05-21 00:03:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "f8901234abcd"
down_revision = "e7f890123456"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_bandit_states",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True, index=True),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("a_json", sa.Text(), nullable=False),
        sa.Column("b_json", sa.Text(), nullable=False),
        sa.Column("update_count", sa.Integer(), server_default="0"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_bandit_states")
