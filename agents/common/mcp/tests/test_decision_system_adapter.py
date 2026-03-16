from __future__ import annotations

import pytest

from agents.common.decision_types import PlannedOperation
from agents.common.mcp.decision_system_adapter import _to_plan
from agents.common.settings import settings


def test_score_decision_aliases_and_default_threshold():
    op = PlannedOperation(
        type="score_decision",
        payload={"decision_id": 5, "scores": [{"goal_id": 1, "score_1_to_5": 4, "rationale": "fit"}]},
        reason="score",
    )
    plan = _to_plan(op)
    assert plan.path == "/decisions/5/score"
    assert plan.body is not None
    assert plan.body["goal_scores"] == [{"goal_id": 1, "score_1_to_5": 4, "rationale": "fit"}]
    assert plan.body["threshold_1_to_5"] == float(settings.decision_threshold_1_to_5)


def test_score_decision_requires_goal_scores():
    op = PlannedOperation(type="score_decision", payload={"decision_id": 5}, reason="score")
    with pytest.raises(ValueError, match="score_decision missing required field\\(s\\): goal_scores"):
        _to_plan(op)
