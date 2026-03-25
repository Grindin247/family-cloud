from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Document(Base):
    __tablename__ = "documents"

    doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    owner_person_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_agent_id: Mapped[str] = mapped_column(String(128), nullable=False, default="FileAgent")
    source_runtime: Mapped[str] = mapped_column(String(64), nullable=False, default="backend")
    visibility_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="family")
    source_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="nextcloud")
    provider_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    excerpt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    media_kind: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    is_directory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    para_bucket: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    extraction_profile: Mapped[str] = mapped_column(String(32), nullable=False, default="metadata")
    ingestion_status: Mapped[str] = mapped_column(String(32), nullable=False, default="indexed")
    tags_jsonb: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    nextcloud_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_note_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_paths_jsonb: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    source_refs_jsonb: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    metadata_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("family_id", "path", name="uq_documents_family_path"),
        UniqueConstraint("family_id", "provider", "provider_file_id", name="uq_documents_family_provider_file"),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.doc_id", ondelete="CASCADE"), primary_key=True)
    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="body")
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    source_ref_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IndexJob(Base):
    __tablename__ = "index_jobs"

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("family_id", "job_type", "dedupe_key", name="uq_index_jobs_dedupe"),)


class DiscoveryCursor(Base):
    __tablename__ = "discovery_cursors"

    cursor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    metadata_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("family_id", "root_path", name="uq_discovery_cursors_family_root"),)


Index("ix_documents_family_kind_updated", Document.family_id, Document.document_kind, Document.updated_at)
Index("ix_documents_family_item_date", Document.family_id, Document.item_type, Document.source_date)
Index("ix_documents_family_para_bucket", Document.family_id, Document.para_bucket)
Index("ix_index_jobs_pending", IndexJob.family_id, IndexJob.status, IndexJob.scheduled_for)
