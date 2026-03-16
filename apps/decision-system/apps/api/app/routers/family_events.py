from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.schemas.family_events import AggregateMetricItem, FamilyEventIngestResponse, FamilyEventResponse, TimeSeriesPoint, TimeSeriesResponse, TimelineItem
from app.services.access import require_family, require_family_member
from app.services.family_events import build_timeline, ingest_family_event, list_family_events, query_counts, query_time_series

router = APIRouter(prefix="/v1", tags=["family-events"])


def _ensure_access(
    db: Session,
    *,
    family_id: int,
    ctx: AuthContext | None,
    x_dev_user: str | None,
) -> None:
    require_family(db, family_id)
    if ctx is not None:
        require_family_member(db, family_id, ctx.email)
    elif x_dev_user:
        require_family_member(db, family_id, x_dev_user.strip().lower())
    else:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User or X-Dev-User)")


@router.post("/events", response_model=FamilyEventIngestResponse, status_code=201)
def create_event(
    payload: dict,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    family_id_raw = payload.get("family_id")
    if family_id_raw is None:
        raise HTTPException(status_code=400, detail="family_id is required in canonical event payload")
    try:
        family_id = int(family_id_raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="family_id must be an integer") from exc
    _ensure_access(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user)
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
    event_type: str | None = Query(default=None),
    subject_id: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    _ensure_access(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user)
    return list_family_events(
        db,
        family_id=family_id,
        domain=domain,
        event_type=event_type,
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
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    _ensure_access(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user)
    return build_timeline(db, family_id=family_id, domain=domain, domains=domains, start=start, end=end, limit=limit)


@router.get("/analytics/counts", response_model=list[AggregateMetricItem])
def get_counts(
    family_id: int = Query(...),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    _ensure_access(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user)
    return query_counts(db, family_id=family_id, start=start, end=end)


@router.get("/analytics/time-series", response_model=TimeSeriesResponse)
def get_time_series(
    family_id: int = Query(...),
    metric: str = Query(...),
    bucket: str = Query(...),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    _ensure_access(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user)
    points = [TimeSeriesPoint.model_validate(item) for item in query_time_series(db, family_id=family_id, metric=metric, bucket=bucket, start=start, end=end)]
    return TimeSeriesResponse(metric=metric, bucket=bucket, points=points)
