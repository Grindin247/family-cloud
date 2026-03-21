from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy import (
    JSON,
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RoleEnum(str, Enum):
    admin = "admin"
    editor = "editor"
    viewer = "viewer"


class ScopeTypeEnum(str, Enum):
    family = "family"
    person = "person"


class VisibilityScopeEnum(str, Enum):
    family = "family"
    personal = "personal"
    admins = "admins"


class GoalStatusEnum(str, Enum):
    active = "active"
    paused = "paused"
    completed = "completed"
    archived = "archived"


class GoalHorizonEnum(str, Enum):
    immediate = "immediate"
    seasonal = "seasonal"
    annual = "annual"
    long_term = "long_term"
    ongoing = "ongoing"


class GoalPolicyEnum(str, Enum):
    family_only = "family_only"
    family_plus_person = "family_plus_person"


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


def _sql_enum(enum_cls: type[Enum], *, name: str) -> SqlEnum:
    return SqlEnum(
        enum_cls,
        name=name,
        values_callable=lambda cls: [item.value for item in cls],
    )


scope_type_sql_enum = _sql_enum(ScopeTypeEnum, name="scopetypeenum")
visibility_scope_sql_enum = _sql_enum(VisibilityScopeEnum, name="visibilityscopeenum")
goal_status_sql_enum = _sql_enum(GoalStatusEnum, name="goalstatusenum")
goal_horizon_sql_enum = _sql_enum(GoalHorizonEnum, name="goalhorizonenum")
goal_policy_sql_enum = _sql_enum(GoalPolicyEnum, name="goalpolicyenum")
decision_status_sql_enum = _sql_enum(DecisionStatusEnum, name="decisionstatusenum")
period_type_sql_enum = _sql_enum(PeriodTypeEnum, name="periodtypeenum")


class Family(Base):
    __tablename__ = "families"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(255), unique=True)
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
    scope_type: Mapped[ScopeTypeEnum] = mapped_column(scope_type_sql_enum, nullable=False, default=ScopeTypeEnum.family)
    owner_person_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("persons.person_id", ondelete="SET NULL"))
    visibility_scope: Mapped[VisibilityScopeEnum] = mapped_column(
        visibility_scope_sql_enum,
        nullable=False,
        default=VisibilityScopeEnum.family,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    action_types_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[GoalStatusEnum] = mapped_column(goal_status_sql_enum, nullable=False, default=GoalStatusEnum.active)
    priority: Mapped[int | None] = mapped_column(Integer)
    horizon: Mapped[GoalHorizonEnum | None] = mapped_column(goal_horizon_sql_enum)
    target_date: Mapped[date | None] = mapped_column(Date)
    success_criteria: Mapped[str | None] = mapped_column(Text)
    review_cadence_days: Mapped[int | None] = mapped_column(Integer)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    external_refs_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    goal_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("weight > 0", name="ck_goals_weight_positive"),
        CheckConstraint("priority IS NULL OR (priority >= 1 AND priority <= 5)", name="ck_goals_priority_range"),
    )


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    scope_type: Mapped[ScopeTypeEnum] = mapped_column(scope_type_sql_enum, nullable=False, default=ScopeTypeEnum.family)
    created_by_person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("persons.person_id"), nullable=False)
    owner_person_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("persons.person_id", ondelete="SET NULL"))
    target_person_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("persons.person_id", ondelete="SET NULL"))
    visibility_scope: Mapped[VisibilityScopeEnum] = mapped_column(
        visibility_scope_sql_enum,
        nullable=False,
        default=VisibilityScopeEnum.family,
    )
    goal_policy: Mapped[GoalPolicyEnum] = mapped_column(goal_policy_sql_enum, nullable=False, default=GoalPolicyEnum.family_only)
    category: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    desired_outcome: Mapped[str | None] = mapped_column(Text)
    constraints_json: Mapped[list[dict[str, object]] | dict[str, object]] = mapped_column(JSON, default=list)
    options_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    cost: Mapped[float | None] = mapped_column(Float)
    urgency: Mapped[int | None] = mapped_column(Integer)
    confidence_1_to_5: Mapped[int | None] = mapped_column(Integer)
    target_date: Mapped[date | None] = mapped_column(Date)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    attachments_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    links_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    context_snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    status: Mapped[DecisionStatusEnum] = mapped_column(decision_status_sql_enum, default=DecisionStatusEnum.draft)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("urgency IS NULL OR (urgency >= 1 AND urgency <= 5)", name="ck_decisions_urgency_range"),
        CheckConstraint(
            "confidence_1_to_5 IS NULL OR (confidence_1_to_5 >= 1 AND confidence_1_to_5 <= 5)",
            name="ck_decisions_confidence_range",
        ),
    )


class DecisionScoreRun(Base):
    __tablename__ = "decision_score_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id"), nullable=False)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    scored_by_person_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("persons.person_id", ondelete="SET NULL"))
    computed_by: Mapped[str] = mapped_column(String(20), nullable=False)
    decision_version: Mapped[int] = mapped_column(Integer, nullable=False)
    goal_policy: Mapped[GoalPolicyEnum] = mapped_column(goal_policy_sql_enum, nullable=False, default=GoalPolicyEnum.family_only)
    threshold_1_to_5: Mapped[float] = mapped_column(Float, nullable=False)
    family_weighted_total_1_to_5: Mapped[float | None] = mapped_column(Float)
    family_weighted_total_0_to_100: Mapped[float | None] = mapped_column(Float)
    person_weighted_total_1_to_5: Mapped[float | None] = mapped_column(Float)
    person_weighted_total_0_to_100: Mapped[float | None] = mapped_column(Float)
    weighted_total_1_to_5: Mapped[float] = mapped_column(Float, nullable=False)
    weighted_total_0_to_100: Mapped[float] = mapped_column(Float, nullable=False)
    routed_to: Mapped[str] = mapped_column(String(32), nullable=False)
    status_after_run: Mapped[str] = mapped_column(String(32), nullable=False)
    context_snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DecisionScoreComponent(Base):
    __tablename__ = "decision_score_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    score_run_id: Mapped[int] = mapped_column(ForeignKey("decision_score_runs.id"), nullable=False)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id"), nullable=False)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"), nullable=False)
    goal_scope_type: Mapped[ScopeTypeEnum] = mapped_column(scope_type_sql_enum, nullable=False)
    goal_owner_person_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("persons.person_id", ondelete="SET NULL"))
    goal_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    goal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    goal_weight: Mapped[float] = mapped_column(Float, nullable=False)
    score_1_to_5: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        CheckConstraint("score_1_to_5 >= 1 AND score_1_to_5 <= 5", name="ck_score_component_range"),
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
    dependencies_json: Mapped[list[int]] = mapped_column(JSON, default=list)


class Period(Base):
    __tablename__ = "periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    type: Mapped[PeriodTypeEnum] = mapped_column(period_type_sql_enum, default=PeriodTypeEnum.quarterly)


class DiscretionaryBudgetLedger(Base):
    __tablename__ = "discretionary_budget_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("persons.person_id"), nullable=False)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


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
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("persons.person_id"), nullable=False)
    allowance: Mapped[int] = mapped_column(Integer, nullable=False, default=2)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_person_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("persons.person_id", ondelete="SET NULL"))
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    changes_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AgentMetricsRollup(Base):
    __tablename__ = "agent_metrics_rollups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(128), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value_number: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


Index("ix_decisions_family_scope_status", Decision.family_id, Decision.scope_type, Decision.status)
Index("ix_decisions_owner_person", Decision.owner_person_id)
Index("ix_decisions_target_person", Decision.target_person_id)
Index("ix_decisions_deleted_at", Decision.deleted_at)
Index("ix_goals_family_scope_status", Goal.family_id, Goal.scope_type, Goal.status)
Index("ix_goals_owner_person", Goal.owner_person_id)
Index("ix_goals_deleted_at", Goal.deleted_at)
Index("ix_decision_score_runs_decision_created", DecisionScoreRun.decision_id, DecisionScoreRun.created_at)
Index("ix_decision_score_components_run_goal", DecisionScoreComponent.score_run_id, DecisionScoreComponent.goal_id, unique=True)
Index("ix_ledger_person_period", DiscretionaryBudgetLedger.person_id, DiscretionaryBudgetLedger.period_id)
Index("ix_periods_family_dates", Period.family_id, Period.start_date, Period.end_date)
Index("ix_member_budget_settings_family_person", MemberBudgetSetting.family_id, MemberBudgetSetting.person_id, unique=True)
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
