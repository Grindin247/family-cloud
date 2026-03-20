"""Standalone family event service tables.

Revision ID: 0001_family_events
Revises:
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_family_events"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "family_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("actor_type", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("subject_type", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("causation_id", sa.String(length=255), nullable=True),
        sa.Column("parent_event_id", sa.String(length=64), nullable=True),
        sa.Column("privacy_classification", sa.String(length=32), nullable=False),
        sa.Column("export_policy", sa.String(length=32), nullable=False),
        sa.Column("tags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("actor_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("subject_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("privacy_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("integrity_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_event_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("legacy_usage_event_id", sa.Integer(), nullable=True),
        sa.Column("legacy_playback_event_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("event_id", name="uq_family_events_event_id"),
    )
    op.create_index("ix_family_events_family_occurred", "family_events", ["family_id", "occurred_at"])
    op.create_index("ix_family_events_family_domain_occurred", "family_events", ["family_id", "domain", "occurred_at"])
    op.create_index("ix_family_events_family_type_occurred", "family_events", ["family_id", "event_type", "occurred_at"])
    op.create_index("ix_family_events_subject_id", "family_events", ["subject_id"])
    op.create_index("ix_family_events_correlation_id", "family_events", ["correlation_id"])
    op.create_index("ix_family_events_payload_gin", "family_events", ["payload_json"], postgresql_using="gin")
    op.create_index("ix_family_events_tags_gin", "family_events", ["tags_json"], postgresql_using="gin")

    op.create_table(
        "family_event_dead_letters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=True),
        sa.Column("subject", sa.String(length=128), nullable=False),
        sa.Column("raw_event_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "family_event_export_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("export_format", sa.String(length=16), nullable=False, server_default="jsonl"),
        sa.Column("options_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_path", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("family_event_export_jobs")
    op.drop_table("family_event_dead_letters")
    op.drop_index("ix_family_events_tags_gin", table_name="family_events")
    op.drop_index("ix_family_events_payload_gin", table_name="family_events")
    op.drop_index("ix_family_events_correlation_id", table_name="family_events")
    op.drop_index("ix_family_events_subject_id", table_name="family_events")
    op.drop_index("ix_family_events_family_type_occurred", table_name="family_events")
    op.drop_index("ix_family_events_family_domain_occurred", table_name="family_events")
    op.drop_index("ix_family_events_family_occurred", table_name="family_events")
    op.drop_table("family_events")
