from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class DecisionCreate(BaseModel):
    family_id: int
    created_by_member_id: int | None = None
    owner_member_id: int | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    cost: float | None = None
    urgency: int | None = Field(default=None, ge=1, le=5)
    target_date: date | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""


class DecisionUpdate(BaseModel):
    owner_member_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    cost: float | None = None
    urgency: int | None = Field(default=None, ge=1, le=5)
    target_date: date | None = None
    tags: list[str] | None = None
    notes: str | None = None


class DecisionResponse(BaseModel):
    id: int
    family_id: int
    created_by_member_id: int
    owner_member_id: int | None
    title: str
    description: str
    cost: float | None
    urgency: int | None
    target_date: date | None
    tags: list[str]
    status: str
    notes: str
    version: int
    created_at: datetime
    score_summary: DecisionScoreSummaryResponse | None = None


class DecisionListResponse(BaseModel):
    items: list[DecisionResponse]


class DecisionGoalScoreResponse(BaseModel):
    goal_id: int
    goal_name: str
    goal_weight: float
    score_1_to_5: int
    rationale: str
    computed_by: str
    version: int


class DecisionScoreSummaryResponse(BaseModel):
    weighted_total_1_to_5: float
    weighted_total_0_to_100: float
    goal_scores: list[DecisionGoalScoreResponse]


class GoalScoreInputPayload(BaseModel):
    goal_id: int
    score_1_to_5: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=1)


class DecisionScoreRequest(BaseModel):
    goal_scores: list[GoalScoreInputPayload] = Field(min_length=1)
    threshold_1_to_5: float = Field(default=4.0, ge=1.0, le=5.0)
    computed_by: str = Field(default="human", pattern="^(human|ai)$")


class DecisionScoreResponse(BaseModel):
    decision_id: int
    weighted_total_1_to_5: float
    weighted_total_0_to_100: float
    threshold_1_to_5: float
    routed_to: str
    status: str
    queue_item_id: int | None = None
