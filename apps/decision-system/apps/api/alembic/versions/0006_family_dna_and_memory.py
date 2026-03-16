"""Family DNA + semantic memory (pgvector).

Revision ID: 0006_family_dna_and_memory
Revises: 0005_keycloak_sync_columns
Create Date: 2026-02-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_family_dna_and_memory"
down_revision = "0005_keycloak_sync_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "family_dna_snapshot",
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(length=255), nullable=False, server_default="system"),
    )

    op.create_table(
        "family_dna_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=255), nullable=False),
        sa.Column("patch_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("sources_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_family_dna_events_family_id", "family_dna_events", ["family_id"])
    op.create_index("ix_family_dna_events_ts", "family_dna_events", ["ts"])

    op.create_table(
        "family_dna_patch_proposals",
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("patch_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="proposed"),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("sources_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_family_dna_patch_proposals_family_id", "family_dna_patch_proposals", ["family_id"])

    op.create_table(
        "memory_documents",
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_refs_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_documents_family_id", "memory_documents", ["family_id"])
    op.create_index("ix_memory_documents_created_at", "memory_documents", ["created_at"])

    # Vector type is provided by pgvector extension; use raw SQL for the column.
    op.create_table(
        "memory_embeddings",
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("memory_documents.doc_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("chunk_id", sa.Integer(), primary_key=True),
        sa.Column("embedding", sa.Text(), nullable=False),  # replaced with vector below
        sa.Column("metadata_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute("ALTER TABLE memory_embeddings ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector")


def downgrade() -> None:
    op.drop_table("memory_embeddings")
    op.drop_index("ix_memory_documents_created_at", table_name="memory_documents")
    op.drop_index("ix_memory_documents_family_id", table_name="memory_documents")
    op.drop_table("memory_documents")

    op.drop_index("ix_family_dna_patch_proposals_family_id", table_name="family_dna_patch_proposals")
    op.drop_table("family_dna_patch_proposals")

    op.drop_index("ix_family_dna_events_ts", table_name="family_dna_events")
    op.drop_index("ix_family_dna_events_family_id", table_name="family_dna_events")
    op.drop_table("family_dna_events")

    op.drop_table("family_dna_snapshot")

