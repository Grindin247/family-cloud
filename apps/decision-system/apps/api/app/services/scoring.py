from dataclasses import dataclass


@dataclass
class GoalScoreInput:
    weight: float
    score: int


def compute_weighted_score(goal_scores: list[GoalScoreInput], normalize_to: int = 100) -> float:
    if not goal_scores:
        return 0.0
    total_weight = sum(item.weight for item in goal_scores)
    if total_weight <= 0:
        raise ValueError("total goal weight must be > 0")
    weighted_sum = sum(item.weight * item.score for item in goal_scores)
    avg_1_to_5 = weighted_sum / total_weight
    if normalize_to == 5:
        return round(avg_1_to_5, 2)
    if normalize_to == 100:
        return round((avg_1_to_5 - 1) * 25, 2)
    raise ValueError("normalize_to must be 5 or 100")


def threshold_outcome(score_1_to_5: float, threshold_1_to_5: float) -> str:
    return "queue" if score_1_to_5 >= threshold_1_to_5 else "needs_work"
