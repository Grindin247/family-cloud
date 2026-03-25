from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class FollowupJobRequest(BaseModel):
    actor: str = Field(min_length=1)
    job_type: Literal["create_question", "mirror_memory", "reindex_document"]
    dedupe_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class FollowupJobResponse(BaseModel):
    job_id: str
    family_id: int
    job_type: str
    status: str
