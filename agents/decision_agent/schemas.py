from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class DecisionIntakeRequest(BaseModel):
    message: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    family_id: int
    # Optional conversation/session key. If omitted, the agent will fall back to a per-user default.
    session_id: str | None = None


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


OperationType = Literal[
    "create_family",
    "update_family",
    "delete_family",
    "create_member",
    "update_member",
    "delete_member",
    "create_goal",
    "update_goal",
    "delete_goal",
    "create_decision",
    "update_decision",
    "delete_decision",
    "score_decision",
    "create_roadmap_item",
    "update_roadmap_item",
    "delete_roadmap_item",
    "update_budget_policy",
    "reset_budget_period",
]


class PlannedOperation(BaseModel):
    type: OperationType
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class DecisionActionPlan(BaseModel):
    intent_summary: str
    operations: list[PlannedOperation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    missing_info: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ExecutionOperationResult(BaseModel):
    type: OperationType
    payload: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None


class PendingConfirmation(BaseModel):
    required: bool = False
    proposal_id: str | None = None
    operations: list[PlannedOperation] = Field(default_factory=list)
    prompt: str | None = None


class DecisionExecution(BaseModel):
    executed_operations: list[ExecutionOperationResult] = Field(default_factory=list)
    failed_operations: list[ExecutionOperationResult] = Field(default_factory=list)


SummaryDomain = Literal["roadmap", "decisions", "goals", "budget"]


class RoadmapSummaryItem(BaseModel):
    roadmap_id: int
    decision_id: int
    decision_title: str
    bucket: str
    status: str
    start_date: date | None = None
    end_date: date | None = None
    dependencies_count: int = 0
    decision_score_1_to_5: float | None = None


class RoadmapSummary(BaseModel):
    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_bucket: dict[str, int] = Field(default_factory=dict)
    items: list[RoadmapSummaryItem] = Field(default_factory=list)


class DecisionSummaryItem(BaseModel):
    decision_id: int
    title: str
    status: str
    urgency: int | None = None
    target_date: date | None = None
    score_1_to_5: float | None = None


class DecisionsSummary(BaseModel):
    total: int = 0
    scored: int = 0
    unscored: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    items: list[DecisionSummaryItem] = Field(default_factory=list)


class GoalSummaryItem(BaseModel):
    goal_id: int
    name: str
    weight: float
    active: bool


class GoalsSummary(BaseModel):
    total: int = 0
    active: int = 0
    active_weight_total: float = 0.0
    items: list[GoalSummaryItem] = Field(default_factory=list)


class BudgetMemberSnapshot(BaseModel):
    member_id: int
    display_name: str
    allowance: int
    used: int
    remaining: int


class BudgetSummarySnapshot(BaseModel):
    threshold_1_to_5: float | None = None
    period_start_date: date | None = None
    period_end_date: date | None = None
    default_allowance: int | None = None
    members: list[BudgetMemberSnapshot] = Field(default_factory=list)


class AgentSummary(BaseModel):
    generated_at: str
    requested_domains: list[SummaryDomain] = Field(default_factory=list)
    included_domains: list[SummaryDomain] = Field(default_factory=list)
    roadmap: RoadmapSummary | None = None
    decisions: DecisionsSummary | None = None
    goals: GoalsSummary | None = None
    budget: BudgetSummarySnapshot | None = None


class DecisionAgentResponse(BaseModel):
    schema_version: str = "2.0"
    status: Literal["executed", "pending_confirmation", "needs_input", "failed"] = "executed"
    intent: str = ""
    plan: DecisionActionPlan | None = None
    execution: DecisionExecution = Field(default_factory=DecisionExecution)
    pending_confirmation: PendingConfirmation = Field(default_factory=PendingConfirmation)
    explanation: str = ""
    summary: AgentSummary | None = None
    artifacts: dict[str, list[int]] = Field(default_factory=dict)
    raw_tool_trace: list[dict[str, Any]] = Field(default_factory=list)

    # Echoed back so clients can persist and send it on follow-ups.
    session_id: str | None = None
    # Legacy fields kept for compatibility.
    draft: DecisionDraft
    cost_estimate: CostEstimate | None = None
    scoring: ScoringResult | None = None
    created_decision: dict[str, Any] | None = None
    updated_decision: dict[str, Any] | None = None
    created_roadmap_items: list[dict[str, Any]] = Field(default_factory=list)
    deconflicts: list[str] = Field(default_factory=list)
    alignment_suggestions: list[str] = Field(default_factory=list)
    legacy_explanation: DecisionExplanation | None = None
