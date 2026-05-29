"""add_summary_embedding_to_events

Revision ID: 7b1c9d2e3a4f
Revises: 6af520bb31e0
Create Date: 2026-05-12 00:00:01.000000

"""
import sqlalchemy as sa

from alembic import op

revision = "7b1c9d2e3a4f"
down_revision = "6af520bb31e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("summary", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("embedding", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_column("embedding")
        batch_op.drop_column("summary")
