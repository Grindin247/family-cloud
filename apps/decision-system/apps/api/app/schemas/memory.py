from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class MemoryDocumentCreate(BaseModel):
    family_id: int
    owner_person_id: str | None = None
    visibility_scope: Literal["personal", "family", "admin_only"] = "family"
    type: Literal["decision", "rationale", "chat", "note", "dna", "roadmap"]
    text: str = Field(min_length=1)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)


class MemoryDocumentResponse(BaseModel):
    doc_id: str
    family_id: int
    owner_person_id: str | None = None
    visibility_scope: str
    type: str
    text: str
    source_refs: list[dict[str, Any]]
    created_at: datetime


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=50)


class MemorySearchHit(BaseModel):
    doc_id: str
    chunk_id: int
    score: float
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)


class MemorySearchResponse(BaseModel):
    items: list[MemorySearchHit]
