"""profile management initial schema

Revision ID: 0001_profile_management_init
Revises:
Create Date: 2026-03-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_profile_management_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profile_records",
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_profile_json", sa.JSON(), nullable=False),
        sa.Column("person_profile_json", sa.JSON(), nullable=False),
        sa.Column("preferences_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("family_id", "person_id", name="uq_profile_records_family_person"),
    )
    op.create_index("ix_profile_records_family_id", "profile_records", ["family_id"])
    op.create_index("ix_profile_records_person_id", "profile_records", ["person_id"])

    op.create_table(
        "relationship_edges",
        sa.Column("relationship_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("source_person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relationship_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_mutual", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("family_id", "source_person_id", "target_person_id", "relationship_type", name="uq_relationship_edges_unique"),
    )
    op.create_index("ix_relationship_edges_family_id", "relationship_edges", ["family_id"])
    op.create_index("ix_relationship_edges_source_person_id", "relationship_edges", ["source_person_id"])
    op.create_index("ix_relationship_edges_target_person_id", "relationship_edges", ["target_person_id"])
    op.create_index("ix_relationship_edges_relationship_type", "relationship_edges", ["relationship_type"])
    op.create_index("ix_relationship_edges_family_source", "relationship_edges", ["family_id", "source_person_id"])
    op.create_index("ix_relationship_edges_family_target", "relationship_edges", ["family_id", "target_person_id"])


def downgrade() -> None:
    op.drop_index("ix_relationship_edges_family_target", table_name="relationship_edges")
    op.drop_index("ix_relationship_edges_family_source", table_name="relationship_edges")
    op.drop_index("ix_relationship_edges_relationship_type", table_name="relationship_edges")
    op.drop_index("ix_relationship_edges_target_person_id", table_name="relationship_edges")
    op.drop_index("ix_relationship_edges_source_person_id", table_name="relationship_edges")
    op.drop_index("ix_relationship_edges_family_id", table_name="relationship_edges")
    op.drop_table("relationship_edges")

    op.drop_index("ix_profile_records_person_id", table_name="profile_records")
    op.drop_index("ix_profile_records_family_id", table_name="profile_records")
    op.drop_table("profile_records")
