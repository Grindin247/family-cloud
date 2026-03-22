from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProfileRecord(Base):
    __tablename__ = "profile_records"

    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    account_profile_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    person_profile_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    preferences_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("family_id", "person_id", name="uq_profile_records_family_person"),
    )


class RelationshipEdge(Base):
    __tablename__ = "relationship_edges"

    relationship_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    target_person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    relationship_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    is_mutual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("family_id", "source_person_id", "target_person_id", "relationship_type", name="uq_relationship_edges_unique"),
    )


Index("ix_relationship_edges_family_source", RelationshipEdge.family_id, RelationshipEdge.source_person_id)
Index("ix_relationship_edges_family_target", RelationshipEdge.family_id, RelationshipEdge.target_person_id)
