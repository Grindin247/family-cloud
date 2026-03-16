from app.services.scoring import GoalScoreInput, compute_weighted_score, threshold_outcome


def test_compute_weighted_score_to_5():
    inputs = [GoalScoreInput(weight=0.6, score=5), GoalScoreInput(weight=0.4, score=3)]
    assert compute_weighted_score(inputs, normalize_to=5) == 4.2


def test_compute_weighted_score_to_100():
    inputs = [GoalScoreInput(weight=1.0, score=5)]
    assert compute_weighted_score(inputs, normalize_to=100) == 100.0


def test_threshold_outcome():
    assert threshold_outcome(3.9, 4.0) == "needs_work"
    assert threshold_outcome(4.0, 4.0) == "queue"
