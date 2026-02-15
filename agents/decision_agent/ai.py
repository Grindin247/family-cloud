from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents.common.settings import settings
from agents.decision_agent.schemas import DecisionDraft, GoalScore


class _DraftResult(BaseModel):
    draft: DecisionDraft


class _QuestionsResult(BaseModel):
    questions: list[str] = Field(default_factory=list)


class _GoalScoresResult(BaseModel):
    goal_scores: list[GoalScore] = Field(min_length=1)
    notes: str = ""


class _AlignmentResult(BaseModel):
    suggestions: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


@dataclass
class DecisionAi:
    """
    PydanticAI-powered helpers used by the decision agent.

    Requires env like:
    - OPENAI_API_KEY
    - PYDANTIC_AI_MODEL (default in agents.common.settings)
    """

    model: str = settings.pydantic_ai_model

    def _draft_agent(self) -> Agent[Any, _DraftResult]:
        return Agent(
            self.model,
            output_type=_DraftResult,
            system_prompt=(
                "You extract a structured decision draft from a single user message.\n"
                "Rules:\n"
                "- Do not invent facts. If unknown, leave fields empty/null.\n"
                "- Title: short, specific.\n"
                "- decision_type must be one of: travel, purchase, life_change, other.\n"
                "- options: include explicit alternatives if present; if only one option is named, include it as the first element.\n"
                "- participants: list names/roles only if mentioned.\n"
                "- target_date: if the user gives a specific date, use it; if they give a range, choose the start date.\n"
                "- constraints: budget/PTO/childcare/accessibility/ports etc if stated.\n"
            ),
        )

    def _questions_agent(self) -> Agent[Any, _QuestionsResult]:
        return Agent(
            self.model,
            output_type=_QuestionsResult,
            system_prompt=(
                "You write concise follow-up questions to fill missing decision details.\n"
                "Rules:\n"
                "- Ask only what is needed to proceed.\n"
                "- Prefer multiple-choice or constrained questions.\n"
                "- Avoid repeating information already known.\n"
            ),
        )

    def _scoring_agent(self) -> Agent[Any, _GoalScoresResult]:
        return Agent(
            self.model,
            output_type=_GoalScoresResult,
            system_prompt=(
                "You score how well a decision aligns with a family's goals.\n"
                "Return a score from 1 to 5 for EACH goal, plus a short rationale per goal.\n"
                "Rules:\n"
                "- Use 3 when the information is insufficient, and explain what would change the score.\n"
                "- Do not use keyword heuristics; reason from the draft and goals.\n"
                "- Be consistent: 5 strongly supports, 1 strongly conflicts.\n"
            ),
        )

    def _alignment_agent(self) -> Agent[Any, _AlignmentResult]:
        return Agent(
            self.model,
            output_type=_AlignmentResult,
            system_prompt=(
                "You help adjust a decision to better align with stated goals when the score is below threshold.\n"
                "Output:\n"
                "- suggestions: concrete adjustments (change scope, timing, budget, option set, constraints)\n"
                "- questions: targeted questions to gather info needed to improve alignment\n"
                "Rules:\n"
                "- Keep it actionable and non-judgmental.\n"
                "- If alignment is already strong, return empty lists.\n"
            ),
        )

    def extract_draft(self, message: str) -> DecisionDraft:
        result = self._draft_agent().run_sync(f"User message:\n{message}")
        return result.output.draft

    def generate_followups(self, *, draft: DecisionDraft, missing: list[str], max_questions: int) -> list[str]:
        if not missing:
            return []
        prompt = (
            f"Decision type: {draft.decision_type}\n"
            f"Known draft: {draft.model_dump(mode='json')}\n"
            f"Missing fields: {missing}\n"
            f"Max questions: {max_questions}\n"
            "Return only the questions list."
        )
        result = self._questions_agent().run_sync(prompt)
        return (result.output.questions or [])[:max_questions]

    def score_goals(self, *, goals: list[dict[str, Any]], draft: DecisionDraft) -> tuple[list[GoalScore], str]:
        prompt = (
            f"Decision draft:\n{draft.model_dump(mode='json')}\n"
            f"Goals (id, name, description, weight):\n{goals}\n"
            "Return goal_scores for every goal id."
        )
        result = self._scoring_agent().run_sync(prompt)
        return result.output.goal_scores, (result.output.notes or "")

    def alignment_help(
        self,
        *,
        draft: DecisionDraft,
        goals: list[dict[str, Any]],
        goal_scores: list[GoalScore],
        weighted_total_1_to_5: float,
        threshold_1_to_5: float,
        max_questions: int,
    ) -> _AlignmentResult:
        prompt = (
            f"Threshold: {threshold_1_to_5}\n"
            f"Weighted total: {weighted_total_1_to_5}\n"
            f"Decision draft:\n{draft.model_dump(mode='json')}\n"
            f"Goals:\n{goals}\n"
            f"Goal scores:\n{[gs.model_dump(mode='json') for gs in goal_scores]}\n"
            f"Max questions: {max_questions}\n"
        )
        result = self._alignment_agent().run_sync(prompt)
        data = result.output
        data.questions = (data.questions or [])[:max_questions]
        return data
