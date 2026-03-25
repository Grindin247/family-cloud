from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.files import SourceRef


class UnifiedSearchRequest(BaseModel):
    family_id: int
    actor: str = Field(min_length=1)
    query: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=25)
    owner_person_id: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    document_kinds: list[Literal["file", "note"]] = Field(default_factory=list)
    preferred_item_types: list[str] = Field(default_factory=list)
    content_types: list[str] = Field(default_factory=list)
    query_tags: list[str] = Field(default_factory=list)
    include_content: bool = True


class UnifiedSearchMatch(BaseModel):
    doc_id: str
    document_kind: Literal["file", "note"]
    path: str
    title: str | None = None
    name: str | None = None
    item_type: str
    role: str
    summary: str | None = None
    excerpt: str | None = None
    content: str | None = None
    content_type: str | None = None
    media_kind: str | None = None
    source_date: date | None = None
    size_bytes: int | None = None
    etag: str | None = None
    file_id: str | None = None
    nextcloud_url: str | None = None
    raw_note_url: str | None = None
    related_paths: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    score: float
    ingestion_status: str
    match_reasons: list[str] = Field(default_factory=list)


class UnifiedSearchResponse(BaseModel):
    items: list[UnifiedSearchMatch] = Field(default_factory=list)
