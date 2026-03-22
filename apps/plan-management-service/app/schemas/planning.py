from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PlanKind = Literal["routine", "habit", "program", "fitness_plan", "meal_plan", "study_plan", "custom"]
PlanStatus = Literal["draft", "active", "paused", "archived"]
OwnerScope = Literal["family", "person"]
ScheduleFrequency = Literal["daily", "weekly"]
Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
PlanInstanceStatus = Literal["scheduled", "done", "skipped", "missed"]
GoalScope = Literal["family", "person"]
ConfidenceLevel = Literal["low", "medium", "high"]
TaskSuggestionStatus = Literal["suggested", "accepted", "dismissed"]


class OrmResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ViewerMembership(BaseModel):
    family_id: int
    family_name: str
    member_id: int
    person_id: str | None = None
    role: str


class ViewerMeResponse(BaseModel):
    authenticated: bool
    email: str | None = None
    memberships: list[ViewerMembership] = Field(default_factory=list)


class ViewerPersonResponse(BaseModel):
    person_id: str
    display_name: str
    role_in_family: str | None = None
    is_admin: bool = False
    status: str
    accounts: dict[str, list[str]] = Field(default_factory=dict)


class ViewerContextResponse(BaseModel):
    family_id: int
    family_slug: str
    person_id: str
    actor_person_id: str
    target_person_id: str
    is_family_admin: bool
    planning_enabled: bool
    primary_email: str | None = None
    directory_account_id: str | None = None
    member_id: int | None = None
    persons: list[ViewerPersonResponse] = Field(default_factory=list)


class PlanningFeatureUpdate(BaseModel):
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)


class PlanningFeatureResponse(BaseModel):
    family_id: int
    feature_key: str
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime | str | None = None


class PlanSchedule(BaseModel):
    timezone: str | None = None
    frequency: ScheduleFrequency | None = None
    interval: int = Field(default=1, ge=1)
    weekdays: list[Weekday] = Field(default_factory=list)
    local_time: time | None = None
    excluded_dates: list[date] = Field(default_factory=list)


class PlanMilestone(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    due_date: date | None = None
    status: str = Field(default="pending", min_length=1, max_length=32)
    notes: str | None = None


class PlanGoalLinkInput(BaseModel):
    goal_id: int = Field(ge=1)
    goal_scope: GoalScope
    weight: float = Field(default=0.0, ge=0.0)
    rationale: str | None = None
    goal_name_snapshot: str | None = Field(default=None, max_length=255)


class PlanGoalLinkResponse(BaseModel):
    goal_id: int
    goal_scope: GoalScope
    weight: float
    rationale: str | None = None
    goal_name_snapshot: str


class TaskSuggestionInput(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    summary: str | None = None
    suggested_for: datetime | None = None
    status: TaskSuggestionStatus = "suggested"
    external_task_ref: str | None = Field(default=None, max_length=255)


class TaskSuggestionResponse(TaskSuggestionInput):
    suggestion_id: str


class GoalOptionResponse(BaseModel):
    goal_id: int
    name: str
    scope_type: str
    owner_person_id: str | None = None
    status: str
    weight: float | None = None
    description: str | None = None


class GoalOptionListResponse(BaseModel):
    items: list[GoalOptionResponse] = Field(default_factory=list)


class PlanCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    summary: str | None = None
    plan_kind: PlanKind
    status: PlanStatus = "draft"
    owner_scope: OwnerScope
    owner_person_id: str | None = None
    participant_person_ids: list[str] = Field(default_factory=list)
    schedule: PlanSchedule = Field(default_factory=PlanSchedule)
    start_date: date | None = None
    end_date: date | None = None
    milestones: list[PlanMilestone] = Field(default_factory=list)
    goal_links: list[PlanGoalLinkInput] = Field(default_factory=list)
    task_suggestions: list[TaskSuggestionInput] = Field(default_factory=list)
    feasibility_summary: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_dates(self) -> "PlanCreate":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class PlanUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    summary: str | None = None
    plan_kind: PlanKind | None = None
    status: PlanStatus | None = None
    owner_scope: OwnerScope | None = None
    owner_person_id: str | None = None
    participant_person_ids: list[str] | None = None
    schedule: PlanSchedule | None = None
    start_date: date | None = None
    end_date: date | None = None
    milestones: list[PlanMilestone] | None = None
    goal_links: list[PlanGoalLinkInput] | None = None
    task_suggestions: list[TaskSuggestionInput] | None = None
    feasibility_summary: dict[str, Any] | None = None


class PlanAlignmentSummary(BaseModel):
    label: str
    linked_goal_count: int
    total_weight: float
    goals: list[PlanGoalLinkResponse] = Field(default_factory=list)
    summary: str


class PlanAdherenceSummary(BaseModel):
    label: str
    completed_count: int
    skipped_count: int
    missed_count: int
    adherence_rate: float
    upcoming_count: int


class PlanInstanceResponse(BaseModel):
    instance_id: str
    plan_id: str
    scheduled_for: datetime
    status: PlanInstanceStatus
    replacement_summary: str | None = None
    created_at: datetime
    updated_at: datetime


class PlanCheckInCreate(BaseModel):
    plan_instance_id: str
    status: PlanInstanceStatus
    note: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    blockers: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel | None = None
    qualitative_update: str | None = None


class PlanCheckInResponse(BaseModel):
    checkin_id: str
    plan_instance_id: str
    status: PlanInstanceStatus
    note: str | None = None
    rating: int | None = None
    blockers: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel | None = None
    qualitative_update: str | None = None
    created_by: str
    created_at: datetime


class PlanResponse(BaseModel):
    plan_id: str
    family_id: int
    title: str
    summary: str | None = None
    plan_kind: PlanKind
    status: PlanStatus
    owner_scope: OwnerScope
    owner_person_id: str | None = None
    participant_person_ids: list[str] = Field(default_factory=list)
    schedule: PlanSchedule = Field(default_factory=PlanSchedule)
    start_date: date | None = None
    end_date: date | None = None
    milestones: list[PlanMilestone] = Field(default_factory=list)
    goal_links: list[PlanGoalLinkResponse] = Field(default_factory=list)
    task_suggestions: list[TaskSuggestionResponse] = Field(default_factory=list)
    alignment_summary: PlanAlignmentSummary
    feasibility_summary: dict[str, Any] = Field(default_factory=dict)
    adherence_summary: PlanAdherenceSummary
    missing_fields: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class PlanListResponse(BaseModel):
    items: list[PlanResponse] = Field(default_factory=list)


class PlanInstanceListResponse(BaseModel):
    items: list[PlanInstanceResponse] = Field(default_factory=list)


class PlanPreviewResponse(BaseModel):
    plan_id: str
    days: int
    items: list[PlanInstanceResponse] = Field(default_factory=list)
    task_suggestions: list[TaskSuggestionResponse] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
