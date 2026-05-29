"""add enriched event fields and user embedding

Revision ID: b3c4d5e6f7a8
Revises: 7b1c9d2e3a4f
Create Date: 2026-05-12 00:00:02.000000

"""
import sqlalchemy as sa

from alembic import op

revision = "b3c4d5e6f7a8"
down_revision = "7b1c9d2e3a4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("tech_stack", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("seniority", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("quality_score", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("hype_score", sa.Integer(), nullable=True))

    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("embedding", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("embedding")

    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_column("hype_score")
        batch_op.drop_column("quality_score")
        batch_op.drop_column("seniority")
        batch_op.drop_column("tech_stack")
