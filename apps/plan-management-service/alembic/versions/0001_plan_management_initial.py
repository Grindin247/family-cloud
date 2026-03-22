"""plan management initial schema

Revision ID: 0001_plan_management_init
Revises:
Create Date: 2026-03-22 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_plan_management_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("plan_kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("owner_scope", sa.String(length=32), nullable=False),
        sa.Column("owner_person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("schedule_json", sa.JSON(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("milestones_json", sa.JSON(), nullable=False),
        sa.Column("feasibility_summary_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_plans_family_id", "plans", ["family_id"])
    op.create_index("ix_plans_status", "plans", ["status"])
    op.create_index("ix_plans_plan_kind", "plans", ["plan_kind"])
    op.create_index("ix_plans_owner_person_id", "plans", ["owner_person_id"])

    op.create_table(
        "plan_participants",
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.plan_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_id", "person_id"),
    )
    op.create_index("ix_plan_participants_family_person", "plan_participants", ["family_id", "person_id"])

    op.create_table(
        "plan_goal_links",
        sa.Column("goal_link_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=False),
        sa.Column("goal_scope", sa.String(length=32), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("goal_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.plan_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("plan_id", "goal_id", name="uq_plan_goal_links_plan_goal"),
    )
    op.create_index("ix_plan_goal_links_family_id", "plan_goal_links", ["family_id"])

    op.create_table(
        "plan_instances",
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("replacement_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.plan_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("plan_id", "scheduled_for", name="uq_plan_instances_plan_scheduled_for"),
    )
    op.create_index("ix_plan_instances_plan_id", "plan_instances", ["plan_id"])
    op.create_index("ix_plan_instances_family_scheduled", "plan_instances", ["family_id", "scheduled_for"])
    op.create_index("ix_plan_instances_status", "plan_instances", ["status"])

    op.create_table(
        "plan_checkins",
        sa.Column("checkin_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("blockers_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=True),
        sa.Column("qualitative_update", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.plan_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_instance_id"], ["plan_instances.instance_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_plan_checkins_plan_id", "plan_checkins", ["plan_id"])
    op.create_index("ix_plan_checkins_instance_id", "plan_checkins", ["plan_instance_id"])

    op.create_table(
        "plan_task_suggestions",
        sa.Column("suggestion_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("suggested_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("external_task_ref", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.plan_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_plan_task_suggestions_plan_id", "plan_task_suggestions", ["plan_id"])


def downgrade() -> None:
    op.drop_index("ix_plan_task_suggestions_plan_id", table_name="plan_task_suggestions")
    op.drop_table("plan_task_suggestions")

    op.drop_index("ix_plan_checkins_instance_id", table_name="plan_checkins")
    op.drop_index("ix_plan_checkins_plan_id", table_name="plan_checkins")
    op.drop_table("plan_checkins")

    op.drop_index("ix_plan_instances_status", table_name="plan_instances")
    op.drop_index("ix_plan_instances_family_scheduled", table_name="plan_instances")
    op.drop_index("ix_plan_instances_plan_id", table_name="plan_instances")
    op.drop_table("plan_instances")

    op.drop_index("ix_plan_goal_links_family_id", table_name="plan_goal_links")
    op.drop_table("plan_goal_links")

    op.drop_index("ix_plan_participants_family_person", table_name="plan_participants")
    op.drop_table("plan_participants")

    op.drop_index("ix_plans_owner_person_id", table_name="plans")
    op.drop_index("ix_plans_plan_kind", table_name="plans")
    op.drop_index("ix_plans_status", table_name="plans")
    op.drop_index("ix_plans_family_id", table_name="plans")
    op.drop_table("plans")
