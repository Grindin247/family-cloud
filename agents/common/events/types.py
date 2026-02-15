from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    """
    Standard event envelope for all agent/event-bus messages.
    """

    id: str
    ts: datetime
    actor: str
    family_id: int
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    source: str

