from __future__ import annotations

from agents.common.mcp.client import HttpToolClient
from agents.common.mcp.decision_system_adapter import DecisionSystemTools


def decision_tools() -> DecisionSystemTools:
    return DecisionSystemTools(http=HttpToolClient())

