from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class QuestionRecord(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    source_agent: Mapped[str] = mapped_column(String(128), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="generic")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    urgency: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer_text: Mapped[str | None] = mapped_column(Text)
    answer_sufficiency_state: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    asked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    context_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    artifact_refs_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    last_delivery_channel: Mapped[str | None] = mapped_column(String(64))
    last_delivery_agent: Mapped[str | None] = mapped_column(String(128))
    current_claim_token: Mapped[str | None] = mapped_column(String(64))
    current_claim_agent: Mapped[str | None] = mapped_column(String(128))
    current_claim_channel: Mapped[str | None] = mapped_column(String(64))
    current_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuestionEvent(Base):
    __tablename__ = "question_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(String(36), nullable=False)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class QuestionDeliveryAttempt(Base):
    __tablename__ = "question_delivery_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(String(36), nullable=False)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_token: Mapped[str | None] = mapped_column(String(64))
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="sent")
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class QuestionEngagementWindow(Base):
    __tablename__ = "question_engagement_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    local_hour: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("family_id", "agent_id", "channel", "local_hour", name="uq_question_engagement_window"),
    )


Index("ix_questions_family_status", QuestionRecord.family_id, QuestionRecord.status)
Index("ix_questions_family_domain_status", QuestionRecord.family_id, QuestionRecord.domain, QuestionRecord.status)
Index("ix_questions_dedupe", QuestionRecord.family_id, QuestionRecord.domain, QuestionRecord.dedupe_key, unique=True)
Index("ix_questions_due_at", QuestionRecord.family_id, QuestionRecord.due_at)
Index("ix_question_events_question", QuestionEvent.question_id, QuestionEvent.created_at)
Index("ix_question_attempts_question", QuestionDeliveryAttempt.question_id, QuestionDeliveryAttempt.sent_at)
Index("ix_question_attempts_family_channel", QuestionDeliveryAttempt.family_id, QuestionDeliveryAttempt.channel, QuestionDeliveryAttempt.sent_at)
