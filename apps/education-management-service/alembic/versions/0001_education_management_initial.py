"""education management initial schema

Revision ID: 0001_education_init
Revises:
Create Date: 2026-03-18 00:00:00.000000
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_education_init"
down_revision = None
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.create_table(
        "learners",
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("birthdate", sa.Date(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_learners_family_id", "learners", ["family_id"])

    op.create_table(
        "domains",
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "skills",
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("domains.domain_id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("parent_skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.skill_id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("domain_id", "code", name="uq_skills_domain_code"),
    )
    op.create_index("ix_skills_domain_id", "skills", ["domain_id"])
    op.create_index("ix_skills_parent_skill_id", "skills", ["parent_skill_id"])

    op.create_table(
        "learning_goals",
        sa.Column("goal_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("learners.learner_id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("domains.domain_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.skill_id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("target_metric_type", sa.String(length=64), nullable=True),
        sa.Column("target_metric_value", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_learning_goals_family_id", "learning_goals", ["family_id"])
    op.create_index("ix_learning_goals_learner_id", "learning_goals", ["learner_id"])
    op.create_index("ix_learning_goals_domain_id", "learning_goals", ["domain_id"])
    op.create_index("ix_learning_goals_skill_id", "learning_goals", ["skill_id"])

    op.create_table(
        "learning_activities",
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("learners.learner_id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("domains.domain_id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.skill_id", ondelete="SET NULL"), nullable=True),
        sa.Column("activity_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("source_session_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_learning_activities_family_id", "learning_activities", ["family_id"])
    op.create_index("ix_learning_activities_learner_id", "learning_activities", ["learner_id"])
    op.create_index("ix_learning_activities_domain_id", "learning_activities", ["domain_id"])
    op.create_index("ix_learning_activities_skill_id", "learning_activities", ["skill_id"])
    op.create_index("ix_learning_activities_occurred_at", "learning_activities", ["occurred_at"])

    op.create_table(
        "assignments",
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("learners.learner_id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("domains.domain_id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.skill_id", ondelete="SET NULL"), nullable=True),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("learning_activities.activity_id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column("rubric_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assignments_family_id", "assignments", ["family_id"])
    op.create_index("ix_assignments_learner_id", "assignments", ["learner_id"])
    op.create_index("ix_assignments_domain_id", "assignments", ["domain_id"])
    op.create_index("ix_assignments_skill_id", "assignments", ["skill_id"])
    op.create_index("ix_assignments_activity_id", "assignments", ["activity_id"])
    op.create_index("ix_assignments_status", "assignments", ["status"])

    op.create_table(
        "assessments",
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("learners.learner_id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("domains.domain_id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.skill_id", ondelete="SET NULL"), nullable=True),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assignments.assignment_id", ondelete="SET NULL"), nullable=True),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("learning_activities.activity_id", ondelete="SET NULL"), nullable=True),
        sa.Column("assessment_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column("percent", sa.Float(), nullable=True),
        sa.Column("confidence_self_report", sa.Float(), nullable=True),
        sa.Column("rubric_json", sa.JSON(), nullable=True),
        sa.Column("graded_by", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assessments_family_id", "assessments", ["family_id"])
    op.create_index("ix_assessments_learner_id", "assessments", ["learner_id"])
    op.create_index("ix_assessments_domain_id", "assessments", ["domain_id"])
    op.create_index("ix_assessments_skill_id", "assessments", ["skill_id"])
    op.create_index("ix_assessments_assignment_id", "assessments", ["assignment_id"])
    op.create_index("ix_assessments_activity_id", "assessments", ["activity_id"])
    op.create_index("ix_assessments_occurred_at", "assessments", ["occurred_at"])

    op.create_table(
        "practice_repetitions",
        sa.Column("repetition_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("learners.learner_id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("domains.domain_id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.skill_id", ondelete="SET NULL"), nullable=True),
        sa.Column("topic_text", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=True),
        sa.Column("performance_score", sa.Float(), nullable=True),
        sa.Column("difficulty_self_report", sa.Float(), nullable=True),
        sa.Column("confidence_self_report", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_practice_repetitions_family_id", "practice_repetitions", ["family_id"])
    op.create_index("ix_practice_repetitions_learner_id", "practice_repetitions", ["learner_id"])
    op.create_index("ix_practice_repetitions_domain_id", "practice_repetitions", ["domain_id"])
    op.create_index("ix_practice_repetitions_skill_id", "practice_repetitions", ["skill_id"])
    op.create_index("ix_practice_repetitions_occurred_at", "practice_repetitions", ["occurred_at"])

    op.create_table(
        "journal_entries",
        sa.Column("journal_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("learners.learner_id", ondelete="CASCADE"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mood_self_report", sa.String(length=64), nullable=True),
        sa.Column("effort_self_report", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_journal_entries_family_id", "journal_entries", ["family_id"])
    op.create_index("ix_journal_entries_learner_id", "journal_entries", ["learner_id"])
    op.create_index("ix_journal_entries_occurred_at", "journal_entries", ["occurred_at"])

    op.create_table(
        "quiz_sessions",
        sa.Column("quiz_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("learners.learner_id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("domains.domain_id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.skill_id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_mode", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column("total_items", sa.Integer(), nullable=True),
        sa.Column("total_score", sa.Float(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quiz_sessions_family_id", "quiz_sessions", ["family_id"])
    op.create_index("ix_quiz_sessions_learner_id", "quiz_sessions", ["learner_id"])
    op.create_index("ix_quiz_sessions_domain_id", "quiz_sessions", ["domain_id"])
    op.create_index("ix_quiz_sessions_skill_id", "quiz_sessions", ["skill_id"])

    op.create_table(
        "quiz_items",
        sa.Column("quiz_item_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("quiz_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quiz_sessions.quiz_id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("item_type", sa.String(length=64), nullable=False),
        sa.Column("correct_answer_json", sa.JSON(), nullable=True),
        sa.Column("rubric_json", sa.JSON(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("quiz_id", "position", name="uq_quiz_items_quiz_position"),
    )
    op.create_index("ix_quiz_items_family_id", "quiz_items", ["family_id"])
    op.create_index("ix_quiz_items_quiz_id", "quiz_items", ["quiz_id"])

    op.create_table(
        "quiz_responses",
        sa.Column("response_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("quiz_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quiz_sessions.quiz_id", ondelete="CASCADE"), nullable=False),
        sa.Column("quiz_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quiz_items.quiz_item_id", ondelete="CASCADE"), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("learners.learner_id", ondelete="CASCADE"), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column("correctness", sa.Boolean(), nullable=True),
        sa.Column("confidence_self_report", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quiz_responses_family_id", "quiz_responses", ["family_id"])
    op.create_index("ix_quiz_responses_quiz_id", "quiz_responses", ["quiz_id"])
    op.create_index("ix_quiz_responses_quiz_item_id", "quiz_responses", ["quiz_item_id"])
    op.create_index("ix_quiz_responses_learner_id", "quiz_responses", ["learner_id"])

    op.create_table(
        "attachments",
        sa.Column("attachment_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("learners.learner_id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("file_ref", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_attachments_family_id", "attachments", ["family_id"])
    op.create_index("ix_attachments_learner_id", "attachments", ["learner_id"])
    op.create_index("ix_attachments_entity_type", "attachments", ["entity_type"])
    op.create_index("ix_attachments_entity_id", "attachments", ["entity_id"])

    op.create_table(
        "progress_snapshots",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("learner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("learners.learner_id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("domains.domain_id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.skill_id", ondelete="SET NULL"), nullable=True),
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("activity_count_7d", sa.Integer(), nullable=False),
        sa.Column("activity_count_30d", sa.Integer(), nullable=False),
        sa.Column("practice_count_7d", sa.Integer(), nullable=False),
        sa.Column("practice_count_30d", sa.Integer(), nullable=False),
        sa.Column("assessment_count_30d", sa.Integer(), nullable=False),
        sa.Column("avg_score_30d", sa.Float(), nullable=True),
        sa.Column("latest_score", sa.Float(), nullable=True),
        sa.Column("latest_assessment_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_minutes_30d", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("family_id", "learner_id", "scope_key", "as_of_date", name="uq_progress_snapshots_scope"),
    )
    op.create_index("ix_progress_snapshots_family_id", "progress_snapshots", ["family_id"])
    op.create_index("ix_progress_snapshots_learner_id", "progress_snapshots", ["learner_id"])
    op.create_index("ix_progress_snapshots_domain_id", "progress_snapshots", ["domain_id"])
    op.create_index("ix_progress_snapshots_skill_id", "progress_snapshots", ["skill_id"])
    op.create_index("ix_progress_snapshots_as_of_date", "progress_snapshots", ["as_of_date"])

    op.create_table(
        "event_log",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("canonical_event_json", sa.JSON(), nullable=False),
        sa.Column("publish_status", sa.String(length=32), nullable=False),
        sa.Column("publish_attempts", sa.Integer(), nullable=False),
        sa.Column("last_publish_error", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_event_log_family_id", "event_log", ["family_id"])
    op.create_index("ix_event_log_event_type", "event_log", ["event_type"])
    op.create_index("ix_event_log_publish_status", "event_log", ["publish_status", "created_at"])

    op.create_table(
        "idempotency_keys",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("route_key", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("family_id", "route_key", "idempotency_key", name="uq_idempotency_family_route_key"),
    )
    op.create_index("ix_idempotency_keys_family_id", "idempotency_keys", ["family_id"])

    domain_table = sa.table(
        "domains",
        sa.column("domain_id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        domain_table,
        [
            {"domain_id": uuid.uuid4(), "code": "math", "name": "Math", "description": "Mathematics and numeracy", "created_at": now},
            {"domain_id": uuid.uuid4(), "code": "reading", "name": "Reading", "description": "Reading and comprehension", "created_at": now},
            {"domain_id": uuid.uuid4(), "code": "writing", "name": "Writing", "description": "Writing and composition", "created_at": now},
            {"domain_id": uuid.uuid4(), "code": "music", "name": "Music", "description": "Music, performance, and theory", "created_at": now},
            {"domain_id": uuid.uuid4(), "code": "home-economics", "name": "Home Economics", "description": "Home economics and daily living", "created_at": now},
            {"domain_id": uuid.uuid4(), "code": "science", "name": "Science", "description": "Science and inquiry", "created_at": now},
            {"domain_id": uuid.uuid4(), "code": "social-studies", "name": "Social Studies", "description": "History, civics, and society", "created_at": now},
            {"domain_id": uuid.uuid4(), "code": "life-skills", "name": "Life Skills", "description": "Life skills and independence", "created_at": now},
            {"domain_id": uuid.uuid4(), "code": "coding", "name": "Coding", "description": "Programming and computational thinking", "created_at": now},
        ],
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_table("event_log")
    op.drop_table("progress_snapshots")
    op.drop_table("attachments")
    op.drop_table("quiz_responses")
    op.drop_table("quiz_items")
    op.drop_table("quiz_sessions")
    op.drop_table("journal_entries")
    op.drop_table("practice_repetitions")
    op.drop_table("assessments")
    op.drop_table("assignments")
    op.drop_table("learning_activities")
    op.drop_table("learning_goals")
    op.drop_table("skills")
    op.drop_table("domains")
    op.drop_table("learners")
