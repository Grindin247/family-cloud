from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FileDocument(Base):
    __tablename__ = "file_documents"

    doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[int] = mapped_column(Integer, ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    file_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    is_directory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    tags_jsonb: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    nextcloud_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_paths_jsonb: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    metadata_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class FileEmbedding(Base):
    __tablename__ = "file_embeddings"

    doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_documents.doc_id", ondelete="CASCADE"), primary_key=True)
    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


Index("ix_file_documents_family_item_date", FileDocument.family_id, FileDocument.item_type, FileDocument.source_date)
Index("ix_file_documents_family_updated", FileDocument.family_id, FileDocument.updated_at)
Index("ix_file_documents_family_media_kind", FileDocument.family_id, FileDocument.media_kind)
