from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentQuestionResponse(BaseModel):
    id: str
    family_id: int
    domain: str
    source_agent: str
    topic: str
    summary: str
    prompt: str
    urgency: str
    topic_type: str
    status: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    due_at: datetime | None = None
    last_asked_at: datetime | None = None
    answer_sufficiency_state: str
    context: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    dedupe_key: str


class AgentQuestionEventResponse(BaseModel):
    id: int
    question_id: str
    family_id: int
    actor: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class CreateAgentQuestionRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=64)
    source_agent: str = Field(min_length=1, max_length=128)
    topic: str = Field(min_length=1, max_length=255)
    summary: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    urgency: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    topic_type: str = Field(default="generic_health", max_length=64)
    expires_at: datetime | None = None
    due_at: datetime | None = None
    answer_sufficiency_state: str = Field(default="unknown", max_length=32)
    context: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str = Field(min_length=1, max_length=255)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)


class UpdateAgentQuestionRequest(BaseModel):
    summary: str | None = None
    prompt: str | None = None
    urgency: str | None = Field(default=None, pattern="^(low|medium|high|critical)$")
    topic_type: str | None = None
    status: str | None = Field(default=None, pattern="^(pending|asked|answered_partial|resolved|expired|dismissed)$")
    expires_at: datetime | None = None
    due_at: datetime | None = None
    answer_sufficiency_state: str | None = None
    context_patch: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] | None = None


class ResolveAgentQuestionRequest(BaseModel):
    status: str = Field(pattern="^(resolved|expired|dismissed|answered_partial)$")
    resolution_note: str | None = None
    answer_sufficiency_state: str | None = None
    context_patch: dict[str, Any] = Field(default_factory=dict)


class MarkAgentQuestionAskedRequest(BaseModel):
    delivery_agent: str = Field(min_length=1, max_length=128)
    delivery_context: dict[str, Any] = Field(default_factory=dict)


class ListAgentQuestionsResponse(BaseModel):
    items: list[AgentQuestionResponse] = Field(default_factory=list)


class AgentMetricItem(BaseModel):
    metric_key: str
    value: float
    unit: str = "count"
    window_start: datetime | None = None
    window_end: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetricsQuery(BaseModel):
    domain: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    metric_keys: list[str] = Field(default_factory=list)


class MetricsQueryResponse(BaseModel):
    items: list[AgentMetricItem] = Field(default_factory=list)


class AgentEvent(BaseModel):
    domain: str = Field(min_length=1, max_length=64)
    source_agent: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1)
    topic: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, max_length=32)
    value_number: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class PlaybackTimelineEvent(BaseModel):
    id: int
    family_id: int
    domain: str
    source_agent: str
    actor: str
    event_type: str
    summary: str
    topic: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PlaybackQuery(BaseModel):
    domain: str | None = None
    event_types: list[str] = Field(default_factory=list)
    start_at: datetime | None = None
    end_at: datetime | None = None
    limit: int = Field(default=100, ge=1, le=500)


class PlaybackQueryResponse(BaseModel):
    items: list[PlaybackTimelineEvent] = Field(default_factory=list)
