from __future__ import annotations

from dataclasses import dataclass

from .schemas import CostEstimate, DecisionDraft


@dataclass
class CostEstimator:
    """
    Budget-safe heuristics first.
    """

    def estimate(self, draft: DecisionDraft) -> CostEstimate | None:
        if draft.decision_type == "travel":
            # Very rough baseline that is intentionally conservative.
            base = 2500.0
            per_person = 1200.0
            party = max(1, len(draft.participants) or 2)
            est = base + per_person * party
            low = est * 0.7
            high = est * 1.4
            return CostEstimate(
                estimate=round(est, 2),
                low=round(low, 2),
                high=round(high, 2),
                assumptions=[
                    f"party_size={party}",
                    "baseline travel estimate (heuristic, not a quote)",
                ]
                + list(draft.assumptions),
                sources=["heuristic"],
            )
        if draft.decision_type == "purchase" and draft.budget:
            est = float(draft.budget)
            return CostEstimate(estimate=est, low=est * 0.9, high=est * 1.1, assumptions=list(draft.assumptions), sources=["user_budget"])
        return None

