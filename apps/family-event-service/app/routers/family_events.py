from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.schemas.family_events import (
    AggregateMetricItem,
    DataQualityResponse,
    DomainSummaryItem,
    EventSequenceResponse,
    FamilyEventIngestResponse,
    FamilyEventResponse,
    PeriodComparisonResponse,
    TimeSeriesPoint,
    TimeSeriesResponse,
    TimelineItem,
    TopTagItem,
)
from app.services.decision_api import ensure_family_access, ensure_family_events_enabled
from app.services.family_events import (
    build_timeline,
    compare_periods,
    get_data_quality_summary,
    get_domain_activity_summary,
    get_event_sequences,
    get_top_tags_or_topics,
    ingest_family_event,
    list_family_events,
    query_counts,
    query_time_series,
)

router = APIRouter(prefix="/v1", tags=["family-events"])


def _is_internal_admin(x_internal_admin_token: str | None) -> bool:
    return bool(x_internal_admin_token and x_internal_admin_token == settings.internal_admin_token)


def _caller_email(x_forwarded_user: str | None, x_dev_user: str | None) -> str | None:
    for candidate in (x_forwarded_user, x_dev_user):
        if candidate and candidate.strip():
            return candidate.strip().lower()
    return None


def _ensure_access(
    *,
    family_id: int,
    x_forwarded_user: str | None,
    x_dev_user: str | None,
    x_internal_admin_token: str | None,
) -> None:
    ensure_family_access(
        family_id=family_id,
        actor_email=_caller_email(x_forwarded_user, x_dev_user),
        internal_admin=_is_internal_admin(x_internal_admin_token),
    )
    ensure_family_events_enabled(
        family_id=family_id,
        actor_email=_caller_email(x_forwarded_user, x_dev_user),
        internal_admin=_is_internal_admin(x_internal_admin_token),
    )


@router.post("/events", response_model=FamilyEventIngestResponse, status_code=201)
def create_event(
    payload: dict,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    family_id_raw = payload.get("family_id")
    if family_id_raw is None:
        raise HTTPException(status_code=400, detail="family_id is required in canonical event payload")
    try:
        family_id = int(family_id_raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="family_id must be an integer") from exc
    _ensure_access(
        family_id=family_id,
        x_forwarded_user=x_forwarded_user,
        x_dev_user=x_dev_user,
        x_internal_admin_token=x_internal_admin_token,
    )
    try:
        record = ingest_family_event(db, payload, subject=f"family.events.{payload.get('domain', 'unknown')}")
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "event": {
            "event_id": record.event_id,
            "family_id": record.family_id,
            "domain": record.domain,
            "event_type": record.event_type,
            "event_version": record.event_version,
            "occurred_at": record.occurred_at,
            "recorded_at": record.recorded_at,
            "actor_id": record.actor_id,
            "actor_type": record.actor_type,
            "subject_id": record.subject_id,
            "subject_type": record.subject_type,
            "correlation_id": record.correlation_id,
            "causation_id": record.causation_id,
            "privacy_classification": record.privacy_classification,
            "export_policy": record.export_policy,
            "tags": record.tags_json,
            "payload": record.payload_json,
            "source": record.source_json,
        },
        "legacy_usage_event_id": record.legacy_usage_event_id,
        "legacy_playback_event_id": record.legacy_playback_event_id,
    }


@router.get("/events", response_model=list[FamilyEventResponse])
def get_events(
    family_id: int = Query(...),
    domain: str | None = Query(default=None),
    domains: list[str] = Query(default=[]),
    event_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    subject_id: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _ensure_access(
        family_id=family_id,
        x_forwarded_user=x_forwarded_user,
        x_dev_user=x_dev_user,
        x_internal_admin_token=x_internal_admin_token,
    )
    return list_family_events(
        db,
        family_id=family_id,
        domain=domain,
        domains=domains,
        event_type=event_type,
        tag=tag,
        subject_id=subject_id,
        actor_id=actor_id,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )


@router.get("/timeline", response_model=list[TimelineItem])
def get_timeline(
    family_id: int = Query(...),
    domain: str | None = Query(default=None),
    domains: list[str] = Query(default=[]),
    event_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _ensure_access(family_id=family_id, x_forwarded_user=x_forwarded_user, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    return build_timeline(db, family_id=family_id, domain=domain, domains=domains, event_type=event_type, tag=tag, start=start, end=end, limit=limit)


@router.get("/analytics/counts", response_model=list[AggregateMetricItem])
def get_counts(
    family_id: int = Query(...),
    domain: str | None = Query(default=None),
    domains: list[str] = Query(default=[]),
    event_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _ensure_access(family_id=family_id, x_forwarded_user=x_forwarded_user, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    return query_counts(db, family_id=family_id, domain=domain, domains=domains, event_type=event_type, tag=tag, start=start, end=end)


@router.get("/analytics/time-series", response_model=TimeSeriesResponse)
def get_time_series(
    family_id: int = Query(...),
    metric: str = Query(...),
    bucket: str = Query(...),
    domain: str | None = Query(default=None),
    domains: list[str] = Query(default=[]),
    event_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _ensure_access(family_id=family_id, x_forwarded_user=x_forwarded_user, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    points = [TimeSeriesPoint.model_validate(item) for item in query_time_series(db, family_id=family_id, metric=metric, bucket=bucket, domain=domain, domains=domains, event_type=event_type, tag=tag, start=start, end=end)]
    return TimeSeriesResponse(metric=metric, bucket=bucket, points=points)


@router.get("/analytics/domain-summary", response_model=list[DomainSummaryItem])
def get_domain_summary(
    family_id: int = Query(...),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _ensure_access(family_id=family_id, x_forwarded_user=x_forwarded_user, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    return get_domain_activity_summary(db, family_id=family_id, start=start, end=end)


@router.get("/analytics/compare-periods", response_model=PeriodComparisonResponse)
def get_period_comparison(
    family_id: int = Query(...),
    metric: str = Query(...),
    current_start: datetime = Query(...),
    current_end: datetime = Query(...),
    baseline_start: datetime = Query(...),
    baseline_end: datetime = Query(...),
    domain: str | None = Query(default=None),
    domains: list[str] = Query(default=[]),
    event_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _ensure_access(family_id=family_id, x_forwarded_user=x_forwarded_user, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    return compare_periods(db, family_id=family_id, metric=metric, current_start=current_start, current_end=current_end, baseline_start=baseline_start, baseline_end=baseline_end, domain=domain, domains=domains, event_type=event_type, tag=tag)


@router.get("/analytics/sequences", response_model=EventSequenceResponse)
def get_sequences(
    family_id: int = Query(...),
    anchor_event_id: str | None = Query(default=None),
    anchor_occurred_at: datetime | None = Query(default=None),
    domain: str | None = Query(default=None),
    domains: list[str] = Query(default=[]),
    before_limit: int = Query(default=5, ge=0, le=50),
    after_limit: int = Query(default=5, ge=0, le=50),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _ensure_access(family_id=family_id, x_forwarded_user=x_forwarded_user, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    return get_event_sequences(db, family_id=family_id, anchor_event_id=anchor_event_id, anchor_occurred_at=anchor_occurred_at, domain=domain, domains=domains, before_limit=before_limit, after_limit=after_limit)


@router.get("/analytics/top-tags", response_model=list[TopTagItem])
def get_top_tags(
    family_id: int = Query(...),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _ensure_access(family_id=family_id, x_forwarded_user=x_forwarded_user, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    return get_top_tags_or_topics(db, family_id=family_id, start=start, end=end, limit=limit)


@router.get("/analytics/data-quality", response_model=DataQualityResponse)
def get_data_quality(
    family_id: int = Query(...),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _ensure_access(family_id=family_id, x_forwarded_user=x_forwarded_user, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    return get_data_quality_summary(db, family_id=family_id, start=start, end=end)
