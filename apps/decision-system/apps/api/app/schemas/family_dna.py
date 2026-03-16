from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JsonPatchOp(BaseModel):
    op: str = Field(pattern="^(add|remove|replace|move|copy|test)$")
    path: str = Field(min_length=1)
    from_: str | None = Field(default=None, alias="from")
    value: Any | None = None


class DnaSnapshotResponse(BaseModel):
    family_id: int
    version: int
    snapshot: dict[str, Any]
    updated_at: datetime
    updated_by: str


class DnaProposeRequest(BaseModel):
    patch: list[JsonPatchOp] = Field(min_length=1)
    rationale: str = Field(default="", max_length=10_000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    sources: list[dict[str, Any]] = Field(default_factory=list)


class DnaProposeResponse(BaseModel):
    proposal_id: str
    status: str


class DnaCommitResponse(BaseModel):
    family_id: int
    version: int
    event_id: str

