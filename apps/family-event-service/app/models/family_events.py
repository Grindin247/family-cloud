from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FamilyEventRecord(Base):
    __tablename__ = "family_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255))
    actor_person_id: Mapped[str | None] = mapped_column(String(64))
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_person_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(255))
    causation_id: Mapped[str | None] = mapped_column(String(255))
    parent_event_id: Mapped[str | None] = mapped_column(String(64))
    privacy_classification: Mapped[str] = mapped_column(String(32), nullable=False)
    export_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    actor_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    subject_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    source_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    privacy_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    integrity_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    raw_event_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    legacy_usage_event_id: Mapped[int | None] = mapped_column(Integer)
    legacy_playback_event_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class FamilyEventDeadLetter(Base):
    __tablename__ = "family_event_dead_letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str | None] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_event_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    error_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class FamilyEventExportJob(Base):
    __tablename__ = "family_event_export_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    export_format: Mapped[str] = mapped_column(String(16), nullable=False, default="jsonl")
    options_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    output_path: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


Index("ix_family_events_family_occurred", FamilyEventRecord.family_id, FamilyEventRecord.occurred_at)
Index("ix_family_events_family_domain_occurred", FamilyEventRecord.family_id, FamilyEventRecord.domain, FamilyEventRecord.occurred_at)
Index("ix_family_events_family_type_occurred", FamilyEventRecord.family_id, FamilyEventRecord.event_type, FamilyEventRecord.occurred_at)
Index("ix_family_events_subject_id", FamilyEventRecord.subject_id)
Index("ix_family_events_actor_id", FamilyEventRecord.actor_id)
Index("ix_family_events_actor_person_id", FamilyEventRecord.actor_person_id)
Index("ix_family_events_subject_person_id", FamilyEventRecord.subject_person_id)
Index("ix_family_events_correlation_id", FamilyEventRecord.correlation_id)
