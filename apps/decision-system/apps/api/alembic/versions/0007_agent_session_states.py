"""Agent session state storage.

Revision ID: 0007_agent_session_states
Revises: 0006_family_dna_and_memory
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_agent_session_states"
down_revision = "0006_family_dna_and_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_session_states",
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("agent_name", sa.String(length=64), primary_key=True),
        sa.Column("actor_email", sa.String(length=255), primary_key=True),
        sa.Column("session_id", sa.String(length=128), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("state_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_session_states_family_updated", "agent_session_states", ["family_id", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_session_states_family_updated", table_name="agent_session_states")
    op.drop_table("agent_session_states")

