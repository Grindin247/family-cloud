from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentSessionUpsertRequest(BaseModel):
    status: str | None = Field(default=None, max_length=32)
    state: dict[str, Any] = Field(default_factory=dict)


class AgentSessionResponse(BaseModel):
    family_id: int
    agent_name: str
    actor_email: str
    session_id: str
    status: str
    state: dict[str, Any]
    created_at: datetime
    updated_at: datetime

