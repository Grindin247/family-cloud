"""add roadmap items table

Revision ID: 0003_roadmap_items
Revises: 0002_vertical_slice
Create Date: 2026-02-08
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_roadmap_items"
down_revision = "0002_vertical_slice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roadmap_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.Integer(), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("bucket", sa.String(length=50), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("dependencies", sa.Text(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_roadmap_items_status_start", "roadmap_items", ["status", "start_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_roadmap_items_status_start", table_name="roadmap_items")
    op.drop_table("roadmap_items")
