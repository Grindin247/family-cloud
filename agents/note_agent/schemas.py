from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


NoteStatus = Literal["ok", "needs_clarification", "error"]
CreatedItemKind = Literal["note", "media", "folder"]
ParaCategory = Literal["Inbox", "Projects", "Areas", "Resources", "Archive"]


class NoteAttachment(BaseModel):
    type: str = Field(min_length=1)
    name: str = Field(min_length=1)
    url: str | None = None
    bytes_base64: str | None = None


class NoteInvokeRequest(BaseModel):
    message: str = ""
    actor: str = Field(min_length=1)
    family_id: int
    session_id: str | None = None
    attachments: list[NoteAttachment] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NoteIngestRequest(BaseModel):
    actor: str = Field(min_length=1)
    family_id: int
    session_id: str | None = None
    max_items: int = Field(default=10, ge=1, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreatedItem(BaseModel):
    path: str
    kind: CreatedItemKind
    url: str | None = None


class NoteAgentResponse(BaseModel):
    status: NoteStatus
    summary: str
    created_items: list[CreatedItem] = Field(default_factory=list)
    actions_taken: list[str] = Field(default_factory=list)
    followups: list[str] | None = None
    debug: dict[str, Any] | None = None


class NoteIngestResponse(BaseModel):
    status: NoteStatus
    summary: str
    created_items: list[CreatedItem] = Field(default_factory=list)
    actions_taken: list[str] = Field(default_factory=list)
    processed_count: int = 0
    skipped_count: int = 0
    cursor: str | None = None
    debug: dict[str, Any] | None = None


class NoteFormattingPlan(BaseModel):
    title: str
    canonical_title: str = ""
    summary: str
    details: str
    action_items: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    destination: ParaCategory = "Inbox"
    collection_path: str = ""
    source_date: str | None = None
    note_kind: str = "note"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    followups: list[str] = Field(default_factory=list)


class IngestSourceContext(BaseModel):
    source_path: str
    original_name: str
    mime_type: str = ""
    modified_at: str | None = None
    raw_text: str = ""
    ocr_text: str = ""
    parsed: bool = False
    encoding: str | None = None
    bytes_base64: str | None = None
    source_date: str | None = None
    source_date_origin: str = "metadata"
    page_count: int | None = None
    extraction_mode: str = "text"
    ocr_quality: str = "unknown"
    analyzed_pages: list[int] = Field(default_factory=list)


class IngestClassification(BaseModel):
    title: str
    canonical_title: str
    summary: str
    details: str
    action_items: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    destination: ParaCategory = "Inbox"
    collection_path: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    note_kind: str = "note"
    media_class: str = "other"
    source_date: str | None = None
    followups: list[str] = Field(default_factory=list)
    classification_method: str = "text"
    evidence_summary: str = ""


class ToolInfo(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class HealthStatus(BaseModel):
    ok: bool
    mcp_reachable: bool
    tools_discovered: list[str] = Field(default_factory=list)
    error: str | None = None
