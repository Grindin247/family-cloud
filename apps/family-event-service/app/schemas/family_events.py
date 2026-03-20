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
    actor_person_id: str | None = None
    actor_type: str
    subject_id: str
    subject_type: str
    subject_person_id: str | None = None
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


class DomainSummaryItem(BaseModel):
    domain: str
    total_events: int
    unique_subjects: int
    unique_actors: int
    event_types: dict[str, int] = Field(default_factory=dict)
    tags: dict[str, int] = Field(default_factory=dict)


class TimeSeriesPoint(BaseModel):
    bucket_start: datetime
    value: float


class TimeSeriesResponse(BaseModel):
    metric: str
    bucket: str
    points: list[TimeSeriesPoint] = Field(default_factory=list)


class PeriodWindow(BaseModel):
    start: datetime
    end: datetime


class PeriodComparisonResponse(BaseModel):
    metric: str
    baseline: PeriodWindow
    current: PeriodWindow
    baseline_value: float
    current_value: float
    delta: float
    delta_pct: float | None = None


class TopTagItem(BaseModel):
    label: str
    source: str
    count: int


class EventSequenceResponse(BaseModel):
    anchor: TimelineItem | None = None
    before: list[TimelineItem] = Field(default_factory=list)
    after: list[TimelineItem] = Field(default_factory=list)


class DataQualityDomainSummary(BaseModel):
    domain: str
    count: int
    sparse: bool = False


class DataQualityResponse(BaseModel):
    family_id: int
    total_events: int
    window_start: datetime | None = None
    window_end: datetime | None = None
    covered_domains: list[str] = Field(default_factory=list)
    missing_domains: list[str] = Field(default_factory=list)
    sparse_domains: list[DataQualityDomainSummary] = Field(default_factory=list)
    duplicate_idempotency_keys: int = 0
    duplicate_correlation_ids: int = 0
    delayed_recording_events: int = 0
    max_recording_delay_hours: float = 0.0
    notes: list[str] = Field(default_factory=list)


class FamilyEventIngestResponse(BaseModel):
    event: FamilyEventResponse
    legacy_usage_event_id: int | None = None
    legacy_playback_event_id: int | None = None
