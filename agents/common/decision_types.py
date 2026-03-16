from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

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
