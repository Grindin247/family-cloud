from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FamilyEventResponse(BaseModel):
    event_id: str
    family_id: int
    domain: str
    event_type: str
    event_version: int
    occurred_at: datetime
    recorded_at: datetime
    actor_id: str | None = None
    actor_type: str
    subject_id: str
    subject_type: str
    correlation_id: str | None = None
    causation_id: str | None = None
    privacy_classification: str
    export_policy: str
    tags: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    source: dict[str, Any] = Field(default_factory=dict)


class TimelineItem(BaseModel):
    occurred_at: datetime
    domain: str
    event_type: str
    title: str
    summary: str
    subject_id: str
    tags: list[str] = Field(default_factory=list)


class AggregateMetricItem(BaseModel):
    metric: str
    value: float


class TimeSeriesPoint(BaseModel):
    bucket_start: datetime
    value: float


class TimeSeriesResponse(BaseModel):
    metric: str
    bucket: str
    points: list[TimeSeriesPoint] = Field(default_factory=list)


class FamilyEventIngestResponse(BaseModel):
    event: FamilyEventResponse
    legacy_usage_event_id: int | None = None
    legacy_playback_event_id: int | None = None
