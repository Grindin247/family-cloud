"""Shared agent ops store.

Revision ID: 0009_agent_ops_store
Revises: 0008_note_retrieval_index
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_agent_ops_store"
down_revision = "0008_note_retrieval_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_questions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.String(length=64), nullable=False),
        sa.Column("source_agent", sa.String(length=128), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("urgency", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("topic_type", sa.String(length=64), nullable=False, server_default="generic_health"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_asked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answer_sufficiency_state", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("context_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("artifact_refs", sa.Text(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_agent_questions_family_status", "agent_questions", ["family_id", "status"])
    op.create_index("ix_agent_questions_domain_status", "agent_questions", ["domain", "status"])
    op.create_index("ix_agent_questions_dedupe", "agent_questions", ["family_id", "domain", "dedupe_key"], unique=True)

    op.create_table(
        "agent_question_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question_id", sa.String(length=36), sa.ForeignKey("agent_questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_question_events_question", "agent_question_events", ["question_id", "created_at"])

    op.create_table(
        "agent_usage_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.String(length=64), nullable=False),
        sa.Column("source_agent", sa.String(length=128), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("value_number", sa.Float(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_usage_events_family_domain", "agent_usage_events", ["family_id", "domain", "created_at"])
    op.create_index("ix_agent_usage_events_event_type", "agent_usage_events", ["event_type", "created_at"])

    op.create_table(
        "agent_metrics_rollups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.String(length=64), nullable=False),
        sa.Column("metric_key", sa.String(length=128), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value_number", sa.Float(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_metrics_rollups_family_domain", "agent_metrics_rollups", ["family_id", "domain", "window_end"])

    op.create_table(
        "agent_playback_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.String(length=64), nullable=False),
        sa.Column("source_agent", sa.String(length=128), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_playback_events_family_domain", "agent_playback_events", ["family_id", "domain", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_playback_events_family_domain", table_name="agent_playback_events")
    op.drop_table("agent_playback_events")
    op.drop_index("ix_agent_metrics_rollups_family_domain", table_name="agent_metrics_rollups")
    op.drop_table("agent_metrics_rollups")
    op.drop_index("ix_agent_usage_events_event_type", table_name="agent_usage_events")
    op.drop_index("ix_agent_usage_events_family_domain", table_name="agent_usage_events")
    op.drop_table("agent_usage_events")
    op.drop_index("ix_agent_question_events_question", table_name="agent_question_events")
    op.drop_table("agent_question_events")
    op.drop_index("ix_agent_questions_dedupe", table_name="agent_questions")
    op.drop_index("ix_agent_questions_domain_status", table_name="agent_questions")
    op.drop_index("ix_agent_questions_family_status", table_name="agent_questions")
    op.drop_table("agent_questions")
