from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.entities import GoalHorizonEnum, GoalStatusEnum, ScopeTypeEnum, VisibilityScopeEnum


class GoalCreate(BaseModel):
    family_id: int
    scope_type: ScopeTypeEnum = ScopeTypeEnum.family
    owner_person_id: str | None = None
    visibility_scope: VisibilityScopeEnum | None = None
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    weight: float = Field(gt=0)
    action_types: list[str] = Field(default_factory=list)
    status: GoalStatusEnum = GoalStatusEnum.active
    priority: int | None = Field(default=None, ge=1, le=5)
    horizon: GoalHorizonEnum | None = None
    target_date: date | None = None
    success_criteria: str | None = None
    review_cadence_days: int | None = Field(default=None, ge=1, le=3650)
    next_review_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    external_refs: list[dict[str, Any]] = Field(default_factory=list)


class GoalUpdate(BaseModel):
    scope_type: ScopeTypeEnum | None = None
    owner_person_id: str | None = None
    visibility_scope: VisibilityScopeEnum | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    weight: float | None = Field(default=None, gt=0)
    action_types: list[str] | None = None
    status: GoalStatusEnum | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    horizon: GoalHorizonEnum | None = None
    target_date: date | None = None
    success_criteria: str | None = None
    review_cadence_days: int | None = Field(default=None, ge=1, le=3650)
    next_review_at: datetime | None = None
    tags: list[str] | None = None
    external_refs: list[dict[str, Any]] | None = None


class GoalResponse(BaseModel):
    id: int
    family_id: int
    scope_type: ScopeTypeEnum
    owner_person_id: str | None
    visibility_scope: VisibilityScopeEnum
    name: str
    description: str
    weight: float
    action_types: list[str]
    status: GoalStatusEnum
    priority: int | None
    horizon: GoalHorizonEnum | None
    target_date: date | None
    success_criteria: str | None
    review_cadence_days: int | None
    next_review_at: datetime | None
    tags: list[str]
    external_refs: list[dict[str, Any]]
    goal_revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class GoalListResponse(BaseModel):
    items: list[GoalResponse]
