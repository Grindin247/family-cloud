"""File-domain index and embeddings.

Revision ID: 0010_file_documents
Revises: 0009_agent_ops_store
Create Date: 2026-03-15
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision = "0010_file_documents"
down_revision = "0009_agent_ops_store"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_documents",
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("source_session_id", sa.String(length=128), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
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
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.Column("file_id", sa.String(length=255), nullable=True),
        sa.Column("is_directory", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tags_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("nextcloud_url", sa.Text(), nullable=True),
        sa.Column("related_paths_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("path", name="uq_file_documents_path"),
    )
    op.create_index("ix_file_documents_family_id", "file_documents", ["family_id"])
    op.create_index("ix_file_documents_actor", "file_documents", ["actor"])
    op.create_index("ix_file_documents_source_session_id", "file_documents", ["source_session_id"])
    op.create_index("ix_file_documents_item_type", "file_documents", ["item_type"])
    op.create_index("ix_file_documents_role", "file_documents", ["role"])
    op.create_index("ix_file_documents_content_type", "file_documents", ["content_type"])
    op.create_index("ix_file_documents_media_kind", "file_documents", ["media_kind"])
    op.create_index("ix_file_documents_source_date", "file_documents", ["source_date"])
    op.create_index("ix_file_documents_etag", "file_documents", ["etag"])
    op.create_index("ix_file_documents_file_id", "file_documents", ["file_id"])
    op.create_index("ix_file_documents_created_at", "file_documents", ["created_at"])
    op.create_index("ix_file_documents_updated_at", "file_documents", ["updated_at"])
    op.create_index("ix_file_documents_family_item_date", "file_documents", ["family_id", "item_type", "source_date"])
    op.create_index("ix_file_documents_family_updated", "file_documents", ["family_id", "updated_at"])
    op.create_index("ix_file_documents_family_media_kind", "file_documents", ["family_id", "media_kind"])

    op.create_table(
        "file_embeddings",
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("file_documents.doc_id", ondelete="CASCADE"), primary_key=True, nullable=False),
        sa.Column("chunk_id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("metadata_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("file_embeddings")
    op.drop_index("ix_file_documents_family_media_kind", table_name="file_documents")
    op.drop_index("ix_file_documents_family_updated", table_name="file_documents")
    op.drop_index("ix_file_documents_family_item_date", table_name="file_documents")
    op.drop_index("ix_file_documents_updated_at", table_name="file_documents")
    op.drop_index("ix_file_documents_created_at", table_name="file_documents")
    op.drop_index("ix_file_documents_file_id", table_name="file_documents")
    op.drop_index("ix_file_documents_etag", table_name="file_documents")
    op.drop_index("ix_file_documents_source_date", table_name="file_documents")
    op.drop_index("ix_file_documents_media_kind", table_name="file_documents")
    op.drop_index("ix_file_documents_content_type", table_name="file_documents")
    op.drop_index("ix_file_documents_role", table_name="file_documents")
    op.drop_index("ix_file_documents_item_type", table_name="file_documents")
    op.drop_index("ix_file_documents_source_session_id", table_name="file_documents")
    op.drop_index("ix_file_documents_actor", table_name="file_documents")
    op.drop_index("ix_file_documents_family_id", table_name="file_documents")
    op.drop_table("file_documents")
