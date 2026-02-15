from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class DecisionIntakeRequest(BaseModel):
    message: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    family_id: int


class DecisionDraft(BaseModel):
    title: str
    description: str
    options: list[str] = Field(default_factory=list)
    target_date: date | None = None
    participants: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    budget: float | None = None
    decision_type: Literal["travel", "purchase", "life_change", "other"] = "other"
    assumptions: list[str] = Field(default_factory=list)


class GoalScore(BaseModel):
    goal_id: int
    goal_name: str
    goal_weight: float
    score_1_to_5: int = Field(ge=1, le=5)
    rationale: str


class ScoringResult(BaseModel):
    weighted_total_1_to_5: float
    weighted_total_0_to_100: float
    threshold_1_to_5: float
    pass_threshold: bool
    goal_scores: list[GoalScore]


class CostEstimate(BaseModel):
    estimate: float
    low: float
    high: float
    assumptions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class DecisionExplanation(BaseModel):
    decision_definition: str
    key_facts_and_assumptions: list[str]
    followups_asked: list[str]
    scoring_notes: str


class DecisionAgentResponse(BaseModel):
    draft: DecisionDraft
    cost_estimate: CostEstimate | None = None
    scoring: ScoringResult | None = None
    created_decision: dict[str, Any] | None = None
    created_roadmap_items: list[dict[str, Any]] = Field(default_factory=list)
    deconflicts: list[str] = Field(default_factory=list)
    alignment_suggestions: list[str] = Field(default_factory=list)
    explanation: DecisionExplanation
