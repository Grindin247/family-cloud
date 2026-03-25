from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


FileItemType = Literal["document", "note", "image", "audio", "video", "archive", "folder", "other"]
FileRole = Literal["user_content", "inbox", "filed", "archive", "attachment", "external_reference"]


def _normalize_path(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return raw
    parts = [segment.strip() for segment in raw.split("/") if segment.strip()]
    normalized: list[str] = []
    for segment in parts:
        if normalized and normalized[-1].lower() == segment.lower():
            continue
        normalized.append(segment)
    return "/" + "/".join(normalized) if normalized else "/"


class SourceRef(BaseModel):
    label: str | None = None
    path: str | None = None
    page: int | None = None
    heading: str | None = None
    section: str | None = None
    sheet_name: str | None = None
    locator_type: str | None = None
    locator_value: str | None = None


class FileIndexRequest(BaseModel):
    family_id: int
    actor: str = Field(min_length=1)
    owner_person_id: str | None = None
    visibility_scope: Literal["personal", "family", "admin_only"] = "family"
    source_session_id: str | None = None
    source_agent_id: str = "FileAgent"
    source_runtime: Literal["backend", "openclaw-subagent", "openclaw-acp"] = "backend"
    path: str = Field(min_length=1)
    name: str | None = None
    item_type: FileItemType
    role: FileRole
    title: str | None = None
    summary: str | None = None
    body_text: str | None = None
    excerpt_text: str | None = None
    content_type: str | None = None
    media_kind: str | None = None
    source_date: date | None = None
    modified_at: datetime | None = None
    size_bytes: int | None = None
    etag: str | None = None
    content_hash: str | None = None
    file_id: str | None = None
    is_directory: bool = False
    tags: list[str] = Field(default_factory=list)
    nextcloud_url: str | None = None
    related_paths: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("path", mode="before")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        return _normalize_path(value)

    @field_validator("related_paths", mode="before")
    @classmethod
    def normalize_related_paths(cls, value: list[str] | None) -> list[str]:
        if not value:
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for path in value:
            path_value = _normalize_path(path)
            if path_value in seen:
                continue
            seen.add(path_value)
            normalized.append(path_value)
        return normalized


class FileIndexResponse(BaseModel):
    doc_id: str
    family_id: int
    path: str
    item_type: FileItemType
    updated_at: datetime
    ingestion_status: str


class FileSearchRequest(BaseModel):
    family_id: int
    actor: str = Field(min_length=1)
    owner_person_id: str | None = None
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    date_from: date | None = None
    date_to: date | None = None
    preferred_item_types: list[FileItemType] = Field(default_factory=list)
    content_types: list[str] = Field(default_factory=list)
    query_tags: list[str] = Field(default_factory=list)
    include_content: bool = True


class FileSearchMatch(BaseModel):
    path: str
    owner_person_id: str | None = None
    visibility_scope: str = "family"
    name: str | None = None
    item_type: FileItemType
    role: FileRole
    title: str | None = None
    summary: str | None = None
    excerpt: str | None = None
    content: str | None = None
    content_type: str | None = None
    media_kind: str | None = None
    source_date: date | None = None
    size_bytes: int | None = None
    etag: str | None = None
    file_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    nextcloud_url: str | None = None
    related_paths: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    score: float
    match_reasons: list[str] = Field(default_factory=list)


class FileSearchResponse(BaseModel):
    items: list[FileSearchMatch] = Field(default_factory=list)


class ProcessInboxRequest(BaseModel):
    actor: str | None = None
    include_dashboard_docs: bool = True
    respect_idle_window: bool = True
    source: str = "api"


class ProcessInboxResult(BaseModel):
    source_path: str
    destination_path: str
    title: str
    folder: str
    item_type: FileItemType | str
    confidence: float
    indexed: bool
    unreadable: bool
    reason: str
    nextcloud_url: str | None = None


class ProcessInboxResponse(BaseModel):
    status: Literal["completed", "partial", "failed"] = "completed"
    processed: int = 0
    indexed: int = 0
    unfiled: int = 0
    skipped_locked: int = 0
    skipped_recent: int = 0
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    results: list[ProcessInboxResult] = Field(default_factory=list)
