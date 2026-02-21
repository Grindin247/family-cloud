from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent

from agents.common.settings import settings
from agents.decision_agent.schemas import DecisionActionPlan, OperationType, PlannedOperation


_ALLOWED_OPERATION_TYPES: list[OperationType] = [
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


class _PlanResult(BaseModel):
    intent_summary: str
    operations: list[PlannedOperation]
    confidence: float
    missing_info: list[str] = []
    assumptions: list[str] = []


@dataclass
class DecisionAi:
    model: str = settings.pydantic_ai_model

    def _planner(self) -> Agent[Any, _PlanResult]:
        return Agent(
            self.model,
            output_type=_PlanResult,
            system_prompt=(
                "You are the family decision operations planner.\n"
                "Primary responsibility: help users capture, clarify, score, and schedule family decisions aligned to goals, budget policy, and roadmap.\n"
                "You translate user intent into an ordered list of valid tool operations.\n"
                "Rules:\n"
                "- Use only supported operation types.\n"
                "- Detect decision candidates from explicit or implied actions (trip, purchase, move, school choice, job change, new habit).\n"
                "- Be proactive, not blocking: if details are missing, create a draft decision first and list targeted follow-up questions in missing_info.\n"
                "- Ask at most 5 follow-up items at once, prioritized by impact on score and feasibility.\n"
                "- Never invent IDs. If an ID is required but unknown, put it in missing_info and skip that operation.\n"
                "- Never mutate goals/weights/budget policy unless the user explicitly asks.\n"
                "- If scoring is requested and goals are available in context, include a score_decision operation.\n"
                "- For score_decision, include goal_scores (one score entry per relevant goal), threshold_1_to_5, and short rationale per goal.\n"
                "- If goals/weights are missing, include a missing_info item requesting goals+weights and do not claim final scoring is complete.\n"
                "- If a decision should be scheduled, include create_roadmap_item with decision_id, bucket, status, and immediate next step in rationale.\n"
                "- Keep payloads minimal and valid for target operations.\n"
                "- Include delete_* operations only when user intent clearly requests deletion.\n"
                "- confidence must be 0..1.\n"
            ),
        )

    def plan_actions(
        self,
        *,
        message: str,
        family_id: int,
        context: dict[str, Any],
    ) -> DecisionActionPlan:
        prompt = (
            f"Family ID: {family_id}\n"
            f"User message:\n{message}\n\n"
            f"Available operation types:\n{_ALLOWED_OPERATION_TYPES}\n\n"
            "Current context snapshots (may be partial):\n"
            f"{context}\n\n"
            "Output operations with explicit payload and short reason for each.\n"
            "Ensure any operation touching family data includes family_id where needed.\n"
            "For decision intake, prefer create_decision/update_decision + score_decision flow with assumptions captured in missing_info/assumptions."
        )
        result = self._planner().run_sync(prompt).output
        return DecisionActionPlan(
            intent_summary=result.intent_summary,
            operations=result.operations,
            confidence=max(0.0, min(1.0, float(result.confidence))),
            missing_info=result.missing_info or [],
            assumptions=result.assumptions or [],
        )
