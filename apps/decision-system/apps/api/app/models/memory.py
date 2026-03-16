from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MemoryDocument(Base):
    __tablename__ = "memory_documents"

    doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[int] = mapped_column(Integer, ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)  # decision|rationale|chat|note|dna|roadmap
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_refs_jsonb: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class MemoryEmbedding(Base):
    __tablename__ = "memory_embeddings"

    doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("memory_documents.doc_id", ondelete="CASCADE"), primary_key=True)
    chunk_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    metadata_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

