from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.entities import (
    DecisionStatusEnum,
    GoalPolicyEnum,
    ScopeTypeEnum,
    VisibilityScopeEnum,
)
from app.schemas.goals import GoalResponse


class DecisionCreate(BaseModel):
    family_id: int
    scope_type: ScopeTypeEnum = ScopeTypeEnum.family
    created_by_person_id: str | None = None
    owner_person_id: str | None = None
    target_person_id: str | None = None
    visibility_scope: VisibilityScopeEnum | None = None
    goal_policy: GoalPolicyEnum | None = None
    category: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    desired_outcome: str | None = None
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    options: list[dict[str, Any]] = Field(default_factory=list)
    cost: float | None = None
    urgency: int | None = Field(default=None, ge=1, le=5)
    confidence_1_to_5: int | None = Field(default=None, ge=1, le=5)
    target_date: date | None = None
    next_review_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    links: list[dict[str, Any]] = Field(default_factory=list)
    context_snapshot: dict[str, Any] = Field(default_factory=dict)


class DecisionUpdate(BaseModel):
    scope_type: ScopeTypeEnum | None = None
    owner_person_id: str | None = None
    target_person_id: str | None = None
    visibility_scope: VisibilityScopeEnum | None = None
    goal_policy: GoalPolicyEnum | None = None
    category: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    desired_outcome: str | None = None
    constraints: list[dict[str, Any]] | None = None
    options: list[dict[str, Any]] | None = None
    cost: float | None = None
    urgency: int | None = Field(default=None, ge=1, le=5)
    confidence_1_to_5: int | None = Field(default=None, ge=1, le=5)
    target_date: date | None = None
    next_review_at: datetime | None = None
    tags: list[str] | None = None
    notes: str | None = None
    attachments: list[dict[str, Any]] | None = None
    links: list[dict[str, Any]] | None = None
    context_snapshot: dict[str, Any] | None = None


class DecisionGoalScoreInput(BaseModel):
    goal_id: int
    score_1_to_5: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=1)


class DecisionScoreRequest(BaseModel):
    goal_scores: list[DecisionGoalScoreInput] = Field(min_length=1)
    threshold_1_to_5: float = Field(default=4.0, ge=1.0, le=5.0)
    computed_by: Literal["human", "ai"] = "human"
    scored_by_person_id: str | None = None
    context_snapshot: dict[str, Any] = Field(default_factory=dict)


class DecisionScoreComponentResponse(BaseModel):
    id: int
    goal_id: int
    goal_name: str
    goal_scope_type: ScopeTypeEnum
    goal_owner_person_id: str | None = None
    goal_revision: int
    goal_weight: float
    score_1_to_5: int
    rationale: str
    created_at: datetime


class DecisionScoreRunResponse(BaseModel):
    id: int
    decision_id: int
    family_id: int
    scored_by_person_id: str | None = None
    computed_by: str
    decision_version: int
    goal_policy: GoalPolicyEnum
    threshold_1_to_5: float
    family_weighted_total_1_to_5: float | None = None
    family_weighted_total_0_to_100: float | None = None
    person_weighted_total_1_to_5: float | None = None
    person_weighted_total_0_to_100: float | None = None
    weighted_total_1_to_5: float
    weighted_total_0_to_100: float
    routed_to: str
    status_after_run: str
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    components: list[DecisionScoreComponentResponse] = Field(default_factory=list)


class DecisionResponse(BaseModel):
    id: int
    family_id: int
    scope_type: ScopeTypeEnum
    created_by_person_id: str
    owner_person_id: str | None = None
    target_person_id: str | None = None
    visibility_scope: VisibilityScopeEnum
    goal_policy: GoalPolicyEnum
    category: str | None = None
    title: str
    description: str
    desired_outcome: str | None = None
    constraints: list[dict[str, Any]]
    options: list[dict[str, Any]]
    cost: float | None = None
    urgency: int | None = None
    confidence_1_to_5: int | None = None
    target_date: date | None = None
    next_review_at: datetime | None = None
    tags: list[str]
    status: DecisionStatusEnum
    notes: str
    attachments: list[dict[str, Any]]
    links: list[dict[str, Any]]
    context_snapshot: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    deleted_at: datetime | None = None
    latest_score_run: DecisionScoreRunResponse | None = None


class DecisionListResponse(BaseModel):
    items: list[DecisionResponse]


class DecisionGoalContextResponse(BaseModel):
    decision_id: int
    family_id: int
    scope_type: ScopeTypeEnum
    goal_policy: GoalPolicyEnum
    target_person_id: str | None = None
    family_goals: list[GoalResponse] = Field(default_factory=list)
    person_goals: list[GoalResponse] = Field(default_factory=list)
    external_context: list[dict[str, Any]] = Field(default_factory=list)


class DecisionScoreRunsResponse(BaseModel):
    items: list[DecisionScoreRunResponse]


class DecisionScoreResponse(BaseModel):
    decision_id: int
    weighted_total_1_to_5: float
    weighted_total_0_to_100: float
    threshold_1_to_5: float
    routed_to: str
    status: str
    queue_item_id: int | None = None
    score_run: DecisionScoreRunResponse
