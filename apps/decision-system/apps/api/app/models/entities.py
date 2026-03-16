from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SqlEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class RoleEnum(str, Enum):
    admin = "admin"
    editor = "editor"
    viewer = "viewer"


class DecisionStatusEnum(str, Enum):
    draft = "Draft"
    scored = "Scored"
    queued = "Queued"
    needs_work = "Needs-Work"
    discretionary_approved = "Discretionary-Approved"
    rejected = "Rejected"
    scheduled = "Scheduled"
    in_progress = "In-Progress"
    done = "Done"
    archived = "Archived"


class PeriodTypeEnum(str, Enum):
    quarterly = "quarterly"
    custom = "custom"


decision_status_sql_enum = SqlEnum(
    DecisionStatusEnum,
    name="decisionstatusenum",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)


class Family(Base):
    __tablename__ = "families"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_source: Mapped[str | None] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(255))
    external_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class FamilyMember(Base):
    __tablename__ = "family_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[RoleEnum] = mapped_column(SqlEnum(RoleEnum), nullable=False)
    external_source: Mapped[str | None] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(255))


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    action_types: Mapped[str] = mapped_column(Text, default="[]")
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    created_by_member_id: Mapped[int] = mapped_column(ForeignKey("family_members.id"), nullable=False)
    owner_member_id: Mapped[int | None] = mapped_column(ForeignKey("family_members.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    cost: Mapped[float | None] = mapped_column(Float)
    urgency: Mapped[int | None] = mapped_column(Integer)
    target_date: Mapped[date | None] = mapped_column(Date)
    tags: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[DecisionStatusEnum] = mapped_column(decision_status_sql_enum, default=DecisionStatusEnum.draft)
    notes: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[str] = mapped_column(Text, default="[]")
    links: Mapped[str] = mapped_column(Text, default="[]")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class DecisionScore(Base):
    __tablename__ = "decision_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id"), nullable=False)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"), nullable=False)
    score_1_to_5: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    computed_by: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("score_1_to_5 >= 1 AND score_1_to_5 <= 5", name="ck_score_range"),
        Index("ix_decision_scores_decision_goal_version", "decision_id", "goal_id", "version"),
    )


class DecisionSuggestion(Base):
    __tablename__ = "decision_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id"), nullable=False)
    suggested_change: Mapped[str] = mapped_column(Text, nullable=False)
    expected_score_impact: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)


class DecisionQueueItem(Base):
    __tablename__ = "decision_queue_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id"), nullable=False, unique=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)


class RoadmapItem(Base):
    __tablename__ = "roadmap_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id"), nullable=False)
    bucket: Mapped[str] = mapped_column(String(50), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    dependencies: Mapped[str] = mapped_column(Text, default="[]")


class Period(Base):
    __tablename__ = "periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    type: Mapped[PeriodTypeEnum] = mapped_column(SqlEnum(PeriodTypeEnum), default=PeriodTypeEnum.quarterly)


class DiscretionaryBudgetLedger(Base):
    __tablename__ = "discretionary_budget_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("family_members.id"), nullable=False)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class BudgetPolicy(Base):
    __tablename__ = "budget_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False, unique=True)
    threshold_1_to_5: Mapped[float] = mapped_column(Float, nullable=False, default=4.0)
    period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    default_allowance: Mapped[int] = mapped_column(Integer, nullable=False, default=2)


class MemberBudgetSetting(Base):
    __tablename__ = "member_budget_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("family_members.id"), nullable=False)
    allowance: Mapped[int] = mapped_column(Integer, nullable=False, default=2)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_member_id: Mapped[int | None] = mapped_column(ForeignKey("family_members.id"))
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    changes_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class AgentQuestion(Base):
    __tablename__ = "agent_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    source_agent: Mapped[str] = mapped_column(String(128), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    urgency: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    topic_type: Mapped[str] = mapped_column(String(64), nullable=False, default="generic_health")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_asked_at: Mapped[datetime | None] = mapped_column(DateTime)
    answer_sufficiency_state: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    context_json: Mapped[str] = mapped_column(Text, default="{}")
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_refs: Mapped[str] = mapped_column(Text, default="[]")


class AgentQuestionEvent(Base):
    __tablename__ = "agent_question_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("agent_questions.id"), nullable=False)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class AgentUsageEvent(Base):
    __tablename__ = "agent_usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    source_agent: Mapped[str] = mapped_column(String(128), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    topic: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str | None] = mapped_column(String(32))
    value_number: Mapped[float | None] = mapped_column(Float)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class AgentMetricsRollup(Base):
    __tablename__ = "agent_metrics_rollups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(128), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    value_number: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class AgentPlaybackEvent(Base):
    __tablename__ = "agent_playback_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    source_agent: Mapped[str] = mapped_column(String(128), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str | None] = mapped_column(String(255))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


Index("ix_decisions_family_status", Decision.family_id, Decision.status)
Index("ix_goals_family_active", Goal.family_id, Goal.active)
Index("ix_ledger_member_period", DiscretionaryBudgetLedger.member_id, DiscretionaryBudgetLedger.period_id)
Index("ix_periods_family_dates", Period.family_id, Period.start_date, Period.end_date)
Index("ix_member_budget_settings_family_member", MemberBudgetSetting.family_id, MemberBudgetSetting.member_id, unique=True)
Index("ix_audit_entity", AuditLog.entity_type, AuditLog.entity_id)
Index("ix_agent_questions_family_status", AgentQuestion.family_id, AgentQuestion.status)
Index("ix_agent_questions_domain_status", AgentQuestion.domain, AgentQuestion.status)
Index("ix_agent_questions_dedupe", AgentQuestion.family_id, AgentQuestion.domain, AgentQuestion.dedupe_key, unique=True)
Index("ix_agent_question_events_question", AgentQuestionEvent.question_id, AgentQuestionEvent.created_at)
Index("ix_agent_usage_events_family_domain", AgentUsageEvent.family_id, AgentUsageEvent.domain, AgentUsageEvent.created_at)
Index("ix_agent_usage_events_event_type", AgentUsageEvent.event_type, AgentUsageEvent.created_at)
Index("ix_agent_metrics_rollups_family_domain", AgentMetricsRollup.family_id, AgentMetricsRollup.domain, AgentMetricsRollup.window_end)
Index("ix_agent_playback_events_family_domain", AgentPlaybackEvent.family_id, AgentPlaybackEvent.domain, AgentPlaybackEvent.created_at)

# Auth/sync lookups
Index("ix_family_members_family_email", FamilyMember.family_id, FamilyMember.email, unique=True)
Index("ix_family_members_family_external", FamilyMember.family_id, FamilyMember.external_source, FamilyMember.external_id, unique=True)
Index("ix_families_external", Family.external_source, Family.external_id, unique=True)
