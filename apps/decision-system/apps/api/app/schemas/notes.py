from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


NoteItemType = Literal["polished", "raw", "attachment"]
NoteRole = Literal["source", "archive", "polished", "attachment", "external_reference"]


def _normalize_note_path(value: str) -> str:
    """Normalize slash usage and collapse adjacent duplicate path segments."""
    raw = (value or "").strip()
    if not raw:
        return raw
    parts = [segment.strip() for segment in raw.split("/") if segment.strip()]
    normalized: list[str] = []
    for segment in parts:
        if normalized and normalized[-1].lower() == segment.lower():
            continue
        normalized.append(segment)
    if not normalized:
        return "/"
    return "/" + "/".join(normalized)


class NoteIndexRequest(BaseModel):
    family_id: int
    actor: str = Field(min_length=1)
    source_session_id: str | None = None
    path: str = Field(min_length=1)
    item_type: NoteItemType
    role: NoteRole
    title: str | None = None
    summary: str | None = None
    body_text: str | None = None
    excerpt_text: str | None = None
    content_type: str | None = None
    source_date: date | None = None
    tags: list[str] = Field(default_factory=list)
    nextcloud_url: str | None = None
    raw_note_url: str | None = None
    related_paths: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("path", mode="before")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        return _normalize_note_path(value)

    @field_validator("related_paths", mode="before")
    @classmethod
    def normalize_related_paths(cls, value: list[str] | None) -> list[str]:
        if not value:
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for path in value:
            path_value = _normalize_note_path(path)
            if path_value in seen:
                continue
            seen.add(path_value)
            normalized.append(path_value)
        return normalized


class NoteIndexResponse(BaseModel):
    doc_id: str
    family_id: int
    path: str
    item_type: NoteItemType
    updated_at: datetime


class NoteSearchRequest(BaseModel):
    family_id: int
    actor: str = Field(min_length=1)
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=10)
    date_from: date | None = None
    date_to: date | None = None
    preferred_item_types: list[NoteItemType] = Field(default_factory=list)
    query_tags: list[str] = Field(default_factory=list)
    include_content: bool = True


class NoteSearchMatch(BaseModel):
    path: str
    item_type: NoteItemType
    role: NoteRole
    title: str | None = None
    summary: str | None = None
    excerpt: str | None = None
    content: str | None = None
    content_type: str | None = None
    source_date: date | None = None
    tags: list[str] = Field(default_factory=list)
    nextcloud_url: str | None = None
    raw_note_url: str | None = None
    related_paths: list[str] = Field(default_factory=list)
    score: float
    match_reasons: list[str] = Field(default_factory=list)


class NoteSearchResponse(BaseModel):
    items: list[NoteSearchMatch] = Field(default_factory=list)
