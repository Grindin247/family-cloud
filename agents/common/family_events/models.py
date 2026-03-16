from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


AllowedDomain = Literal["decision", "task", "file", "note"]
AllowedRuntime = Literal["openclaw-subagent", "openclaw-acp", "backend"]
AllowedPrivacyClassification = Literal["private", "family", "research", "commercial"]
AllowedExportPolicy = Literal["never", "restricted", "anonymizable", "exportable"]


class EventActor(BaseModel):
    actor_type: str = Field(min_length=1, max_length=64)
    actor_id: str = Field(min_length=1, max_length=255)
    display_role: str | None = Field(default=None, max_length=128)


class EventSubject(BaseModel):
    subject_type: str = Field(min_length=1, max_length=64)
    subject_id: str = Field(min_length=1, max_length=255)


class EventSource(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    runtime: AllowedRuntime
    agent_version: str | None = Field(default=None, max_length=64)
    channel: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, max_length=255)
    session_id: str | None = Field(default=None, max_length=255)


class EventCorrelation(BaseModel):
    correlation_id: str | None = Field(default=None, max_length=255)
    causation_id: str | None = Field(default=None, max_length=255)
    parent_event_id: str | None = Field(default=None, max_length=64)


class EventPrivacy(BaseModel):
    classification: AllowedPrivacyClassification = "family"
    contains_pii: bool = False
    contains_health_data: bool = False
    contains_financial_data: bool = False
    contains_child_data: bool = False
    contains_free_text: bool = False
    export_policy: AllowedExportPolicy = "restricted"


class EventIntegrity(BaseModel):
    producer: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=255)


class FamilyEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=64)
    schema_version: int = Field(default=1, ge=1)
    occurred_at: datetime
    recorded_at: datetime
    family_id: int = Field(ge=1)
    domain: AllowedDomain
    event_type: str = Field(min_length=3, max_length=128)
    event_version: int = Field(default=1, ge=1)
    actor: EventActor
    subject: EventSubject
    source: EventSource
    correlation: EventCorrelation = Field(default_factory=EventCorrelation)
    privacy: EventPrivacy = Field(default_factory=EventPrivacy)
    payload: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    integrity: EventIntegrity | None = None

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        return [item.strip().lower() for item in value if item and item.strip()]

    @model_validator(mode="after")
    def _validate_event_type(self) -> "FamilyEvent":
        expected_prefix = f"{self.subject.subject_type}."
        if not self.event_type.startswith(expected_prefix):
            raise ValueError(f"event_type must start with '{expected_prefix}'")
        if self.source.agent_id not in {"DecisionAgent", "TaskAgent", "FileAgent"}:
            raise ValueError("source.agent_id must be one of DecisionAgent, TaskAgent, or FileAgent")
        return self
