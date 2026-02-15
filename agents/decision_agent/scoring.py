from __future__ import annotations

from dataclasses import dataclass, field

from agents.common.settings import settings

from .ai import DecisionAi
from .schemas import GoalScore, ScoringResult


def _weighted_totals(goal_scores: list[GoalScore]) -> tuple[float, float]:
    weight_total = sum(gs.goal_weight for gs in goal_scores) or 0.0
    if weight_total <= 0:
        return 0.0, 0.0
    weighted_sum = sum(gs.goal_weight * gs.score_1_to_5 for gs in goal_scores)
    weighted_1_to_5 = weighted_sum / weight_total
    weighted_0_to_100 = (weighted_1_to_5 / 5.0) * 100.0
    return weighted_1_to_5, weighted_0_to_100


@dataclass
class Scorer:
    threshold_1_to_5: float = settings.decision_threshold_1_to_5
    ai: DecisionAi = field(default_factory=DecisionAi)

    def score(self, goals: list[dict], draft_title: str, draft_description: str, *, draft_obj=None) -> tuple[ScoringResult, str]:
        """
        AI-based goal scoring. No keyword heuristics.

        `draft_obj` may be provided (DecisionDraft) to include richer fields; if omitted, the AI sees title/description.
        """
        if draft_obj is None:
            from .schemas import DecisionDraft

            draft_obj = DecisionDraft(title=draft_title, description=draft_description)

        goal_scores, notes = self.ai.score_goals(goals=goals, draft=draft_obj)

        # Ensure stable weights/names from source goals (not the model).
        by_id = {int(g["id"]): g for g in goals}
        normalized: list[GoalScore] = []
        for gs in goal_scores:
            g = by_id.get(int(gs.goal_id))
            if not g:
                continue
            normalized.append(
                GoalScore(
                    goal_id=int(g["id"]),
                    goal_name=str(g["name"]),
                    goal_weight=float(g.get("weight", 1.0)),
                    score_1_to_5=int(gs.score_1_to_5),
                    rationale=str(gs.rationale),
                )
            )

        weighted_1_to_5, weighted_0_to_100 = _weighted_totals(normalized)
        pass_threshold = weighted_1_to_5 >= float(self.threshold_1_to_5)
        return (
            ScoringResult(
                weighted_total_1_to_5=round(weighted_1_to_5, 3),
                weighted_total_0_to_100=round(weighted_0_to_100, 1),
                threshold_1_to_5=float(self.threshold_1_to_5),
                pass_threshold=pass_threshold,
                goal_scores=normalized,
            ),
            notes,
        )
