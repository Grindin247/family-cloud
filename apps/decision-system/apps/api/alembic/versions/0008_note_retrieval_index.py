"""Note retrieval index tables.

Revision ID: 0008_note_retrieval_index
Revises: 0007_agent_session_states
Create Date: 2026-03-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_note_retrieval_index"
down_revision = "0007_agent_session_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "note_documents",
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("source_session_id", sa.String(length=128), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("excerpt_text", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("source_date", sa.Date(), nullable=True),
        sa.Column("tags_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("nextcloud_url", sa.Text(), nullable=True),
        sa.Column("raw_note_url", sa.Text(), nullable=True),
        sa.Column("related_paths_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("path", name="uq_note_documents_path"),
    )
    op.create_index("ix_note_documents_family_id", "note_documents", ["family_id"])
    op.create_index("ix_note_documents_actor", "note_documents", ["actor"])
    op.create_index("ix_note_documents_source_session_id", "note_documents", ["source_session_id"])
    op.create_index("ix_note_documents_item_type", "note_documents", ["item_type"])
    op.create_index("ix_note_documents_role", "note_documents", ["role"])
    op.create_index("ix_note_documents_source_date", "note_documents", ["source_date"])
    op.create_index("ix_note_documents_created_at", "note_documents", ["created_at"])
    op.create_index("ix_note_documents_updated_at", "note_documents", ["updated_at"])
    op.create_index("ix_note_documents_family_item_date", "note_documents", ["family_id", "item_type", "source_date"])
    op.create_index("ix_note_documents_family_updated", "note_documents", ["family_id", "updated_at"])

    op.create_table(
        "note_embeddings",
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("note_documents.doc_id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("metadata_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("doc_id", "chunk_id"),
    )
    op.execute("ALTER TABLE note_embeddings ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector")


def downgrade() -> None:
    op.drop_table("note_embeddings")
    op.drop_index("ix_note_documents_family_updated", table_name="note_documents")
    op.drop_index("ix_note_documents_family_item_date", table_name="note_documents")
    op.drop_index("ix_note_documents_updated_at", table_name="note_documents")
    op.drop_index("ix_note_documents_created_at", table_name="note_documents")
    op.drop_index("ix_note_documents_source_date", table_name="note_documents")
    op.drop_index("ix_note_documents_role", table_name="note_documents")
    op.drop_index("ix_note_documents_item_type", table_name="note_documents")
    op.drop_index("ix_note_documents_source_session_id", table_name="note_documents")
    op.drop_index("ix_note_documents_actor", table_name="note_documents")
    op.drop_index("ix_note_documents_family_id", table_name="note_documents")
    op.drop_table("note_documents")
