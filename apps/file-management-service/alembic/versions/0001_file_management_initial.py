"""file management initial schema

Revision ID: 0001_file_management_initial
Revises:
Create Date: 2026-03-24 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision = "0001_file_management_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("owner_person_id", sa.String(length=64), nullable=True),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("source_agent_id", sa.String(length=128), nullable=False),
        sa.Column("source_runtime", sa.String(length=64), nullable=False),
        sa.Column("visibility_scope", sa.String(length=32), nullable=False),
        sa.Column("source_session_id", sa.String(length=128), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_file_id", sa.String(length=255), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("document_kind", sa.String(length=16), nullable=False),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("excerpt_text", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("media_kind", sa.String(length=64), nullable=True),
        sa.Column("source_date", sa.Date(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("is_directory", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("para_bucket", sa.String(length=32), nullable=True),
        sa.Column("extraction_profile", sa.String(length=32), nullable=False),
        sa.Column("ingestion_status", sa.String(length=32), nullable=False),
        sa.Column("tags_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("nextcloud_url", sa.Text(), nullable=True),
        sa.Column("raw_note_url", sa.Text(), nullable=True),
        sa.Column("related_paths_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_refs_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("family_id", "path", name="uq_documents_family_path"),
        sa.UniqueConstraint("family_id", "provider", "provider_file_id", name="uq_documents_family_provider_file"),
    )
    op.create_index("ix_documents_family_id", "documents", ["family_id"])
    op.create_index("ix_documents_owner_person_id", "documents", ["owner_person_id"])
    op.create_index("ix_documents_provider_file_id", "documents", ["provider_file_id"])
    op.create_index("ix_documents_document_kind", "documents", ["document_kind"])
    op.create_index("ix_documents_item_type", "documents", ["item_type"])
    op.create_index("ix_documents_role", "documents", ["role"])
    op.create_index("ix_documents_content_type", "documents", ["content_type"])
    op.create_index("ix_documents_media_kind", "documents", ["media_kind"])
    op.create_index("ix_documents_source_date", "documents", ["source_date"])
    op.create_index("ix_documents_modified_at", "documents", ["modified_at"])
    op.create_index("ix_documents_etag", "documents", ["etag"])
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])
    op.create_index("ix_documents_para_bucket", "documents", ["family_id", "para_bucket"])
    op.create_index("ix_documents_family_kind_updated", "documents", ["family_id", "document_kind", "updated_at"])
    op.create_index("ix_documents_family_item_date", "documents", ["family_id", "item_type", "source_date"])

    op.create_table(
        "document_chunks",
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.doc_id", ondelete="CASCADE"), primary_key=True, nullable=False),
        sa.Column("chunk_id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("chunk_kind", sa.String(length=32), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column("source_ref_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "index_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("family_id", "job_type", "dedupe_key", name="uq_index_jobs_dedupe"),
    )
    op.create_index("ix_index_jobs_pending", "index_jobs", ["family_id", "status", "scheduled_for"])

    op.create_table(
        "discovery_cursors",
        sa.Column("cursor_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("family_id", "root_path", name="uq_discovery_cursors_family_root"),
    )
    op.create_index("ix_discovery_cursors_family_id", "discovery_cursors", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_discovery_cursors_family_id", table_name="discovery_cursors")
    op.drop_table("discovery_cursors")

    op.drop_index("ix_index_jobs_pending", table_name="index_jobs")
    op.drop_table("index_jobs")

    op.drop_table("document_chunks")

    op.drop_index("ix_documents_family_item_date", table_name="documents")
    op.drop_index("ix_documents_family_kind_updated", table_name="documents")
    op.drop_index("ix_documents_para_bucket", table_name="documents")
    op.drop_index("ix_documents_content_hash", table_name="documents")
    op.drop_index("ix_documents_etag", table_name="documents")
    op.drop_index("ix_documents_modified_at", table_name="documents")
    op.drop_index("ix_documents_source_date", table_name="documents")
    op.drop_index("ix_documents_media_kind", table_name="documents")
    op.drop_index("ix_documents_content_type", table_name="documents")
    op.drop_index("ix_documents_role", table_name="documents")
    op.drop_index("ix_documents_item_type", table_name="documents")
    op.drop_index("ix_documents_document_kind", table_name="documents")
    op.drop_index("ix_documents_provider_file_id", table_name="documents")
    op.drop_index("ix_documents_owner_person_id", table_name="documents")
    op.drop_index("ix_documents_family_id", table_name="documents")
    op.drop_table("documents")
