from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FamilyDnaSnapshot(Base):
    __tablename__ = "family_dna_snapshot"

    family_id: Mapped[int] = mapped_column(Integer, ForeignKey("families.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False, default="system")


class FamilyDnaEvent(Base):
    __tablename__ = "family_dna_events"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[int] = mapped_column(Integer, ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(255), nullable=False)
    patch_jsonb: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    sources_jsonb: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    result_version: Mapped[int] = mapped_column(Integer, nullable=False)


class FamilyDnaPatchProposal(Base):
    __tablename__ = "family_dna_patch_proposals"

    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[int] = mapped_column(Integer, ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    patch_jsonb: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")  # proposed|committed|rejected|canceled
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    sources_jsonb: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)

