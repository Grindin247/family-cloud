"""question management initial schema

Revision ID: 0001_question_management_init
Revises:
Create Date: 2026-03-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_question_management_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "questions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=64), nullable=False),
        sa.Column("source_agent", sa.String(length=128), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("urgency", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_asked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answer_sufficiency_state", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("asked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("context_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("artifact_refs_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("last_delivery_channel", sa.String(length=64), nullable=True),
        sa.Column("last_delivery_agent", sa.String(length=128), nullable=True),
        sa.Column("current_claim_token", sa.String(length=64), nullable=True),
        sa.Column("current_claim_agent", sa.String(length=128), nullable=True),
        sa.Column("current_claim_channel", sa.String(length=64), nullable=True),
        sa.Column("current_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_claim_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_questions_family_status", "questions", ["family_id", "status"])
    op.create_index("ix_questions_family_domain_status", "questions", ["family_id", "domain", "status"])
    op.create_index("ix_questions_dedupe", "questions", ["family_id", "domain", "dedupe_key"], unique=True)
    op.create_index("ix_questions_due_at", "questions", ["family_id", "due_at"])

    op.create_table(
        "question_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_question_events_question", "question_events", ["question_id", "created_at"])

    op.create_table(
        "question_delivery_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False, server_default="sent"),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_question_attempts_question", "question_delivery_attempts", ["question_id", "sent_at"])
    op.create_index("ix_question_attempts_family_channel", "question_delivery_attempts", ["family_id", "channel", "sent_at"])

    op.create_table(
        "question_engagement_windows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("local_hour", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("family_id", "agent_id", "channel", "local_hour", name="uq_question_engagement_window"),
    )


def downgrade() -> None:
    op.drop_table("question_engagement_windows")
    op.drop_index("ix_question_attempts_family_channel", table_name="question_delivery_attempts")
    op.drop_index("ix_question_attempts_question", table_name="question_delivery_attempts")
    op.drop_table("question_delivery_attempts")
    op.drop_index("ix_question_events_question", table_name="question_events")
    op.drop_table("question_events")
    op.drop_index("ix_questions_due_at", table_name="questions")
    op.drop_index("ix_questions_dedupe", table_name="questions")
    op.drop_index("ix_questions_family_domain_status", table_name="questions")
    op.drop_index("ix_questions_family_status", table_name="questions")
    op.drop_table("questions")
