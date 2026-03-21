from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.schemas.family_events import (
    AggregateMetricItem,
    DataQualityResponse,
    EventMemberScope,
    EventFilterOptionsResponse,
    EventSearchResponse,
    EventViewerContextResponse,
    EventViewerMeResponse,
    DomainSummaryItem,
    EventSequenceResponse,
    FamilyEventIngestResponse,
    FamilyEventResponse,
    PeriodComparisonResponse,
    TimeSeriesPoint,
    TimeSeriesResponse,
    TimelineItem,
    TopTagItem,
    ViewerPersonResponse,
)
from app.services.decision_api import (
    ensure_family_access,
    ensure_family_events_enabled,
    get_family_context,
    get_family_persons,
    get_me,
)
from app.services.family_events import (
    build_timeline,
    compare_periods,
    get_data_quality_summary,
    get_domain_activity_summary,
    get_event_sequences,
    get_top_tags_or_topics,
    ingest_family_event,
    list_event_filter_options,
    list_family_events,
    query_counts,
    query_time_series,
    search_family_events,
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


def _resolve_person_scope_tokens(
    *,
    family_id: int,
    actor_email: str,
    member_scope: EventMemberScope,
    person_id: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], set[str]]:
    context = get_family_context(family_id=family_id, actor_email=actor_email)
    persons = get_family_persons(family_id=family_id, actor_email=actor_email)
    person_map = {str(item.get("person_id") or "").strip(): item for item in persons if item.get("person_id")}
    active_person_id = str(context.get("person_id") or "").strip()
    if not active_person_id:
        raise HTTPException(status_code=502, detail="family context missing person_id")
    if member_scope == "all":
        if not bool(context.get("is_family_admin")):
            raise HTTPException(status_code=403, detail="admin role required for cross-member event access")
        return context, persons, set()

    selected_person_id = active_person_id
    if member_scope == "person":
        selected_person_id = str(person_id or "").strip()
        if not selected_person_id:
            raise HTTPException(status_code=400, detail="person_id is required when member_scope=person")
        if selected_person_id != active_person_id and not bool(context.get("is_family_admin")):
            raise HTTPException(status_code=403, detail="admin role required for cross-member event access")

    selected_person = person_map.get(selected_person_id)
    if selected_person is None:
        raise HTTPException(status_code=400, detail="person_id must belong to the family")

    tokens: set[str] = {selected_person_id.lower()}
    for values in (selected_person.get("accounts") or {}).values():
        if not isinstance(values, list):
            continue
        for value in values:
            token = str(value or "").strip().lower()
            if token:
                tokens.add(token)
    primary_email = str(selected_person.get("accounts", {}).get("email", [None])[0] or "").strip().lower()
    if primary_email:
        tokens.add(primary_email)
    return context, persons, tokens


def _viewer_person(item: dict[str, Any]) -> ViewerPersonResponse:
    return ViewerPersonResponse(
        person_id=str(item.get("person_id")),
        display_name=str(item.get("display_name") or item.get("canonical_name") or item.get("person_id")),
        role_in_family=item.get("role_in_family"),
        is_admin=bool(item.get("is_admin")),
        status=str(item.get("status") or "active"),
    )


@router.get("/me", response_model=EventViewerMeResponse)
def viewer_me(
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    payload = get_me(actor_email=actor_email)
    return EventViewerMeResponse.model_validate(payload)


@router.get("/families/{family_id}/viewer-context", response_model=EventViewerContextResponse)
def viewer_context(
    family_id: int,
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
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    context = get_family_context(family_id=family_id, actor_email=actor_email)
    persons = get_family_persons(family_id=family_id, actor_email=actor_email)
    return EventViewerContextResponse(
        family_id=family_id,
        family_slug=str(context.get("family_slug") or ""),
        person_id=str(context.get("person_id") or ""),
        actor_person_id=str(context.get("actor_person_id") or ""),
        target_person_id=str(context.get("target_person_id") or context.get("person_id") or ""),
        is_family_admin=bool(context.get("is_family_admin")),
        primary_email=context.get("primary_email"),
        directory_account_id=context.get("directory_account_id"),
        member_id=context.get("member_id"),
        persons=[_viewer_person(item) for item in persons if str(item.get("status") or "active") == "active"],
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


@router.get("/events/search", response_model=EventSearchResponse)
def search_events(
    family_id: int = Query(...),
    member_scope: EventMemberScope | None = Query(default=None),
    person_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    subject_id: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=250),
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
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    if not actor_email:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User or X-Dev-User)")
    base_context = get_family_context(family_id=family_id, actor_email=actor_email)
    effective_scope = member_scope or ("all" if bool(base_context.get("is_family_admin")) else "mine")
    _, _, scope_tokens = _resolve_person_scope_tokens(
        family_id=family_id,
        actor_email=actor_email,
        member_scope=effective_scope,
        person_id=person_id,
    )
    return EventSearchResponse.model_validate(
        search_family_events(
            db,
            family_id=family_id,
            domain=domain,
            event_type=event_type,
            tag=tag,
            subject_id=subject_id,
            actor_id=actor_id,
            member_scope_tokens=scope_tokens,
            query=q,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/events/filter-options", response_model=EventFilterOptionsResponse)
def event_filter_options(
    family_id: int = Query(...),
    member_scope: EventMemberScope | None = Query(default=None),
    person_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    subject_id: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
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
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    if not actor_email:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User or X-Dev-User)")
    base_context = get_family_context(family_id=family_id, actor_email=actor_email)
    effective_scope = member_scope or ("all" if bool(base_context.get("is_family_admin")) else "mine")
    _, _, scope_tokens = _resolve_person_scope_tokens(
        family_id=family_id,
        actor_email=actor_email,
        member_scope=effective_scope,
        person_id=person_id,
    )
    return EventFilterOptionsResponse.model_validate(
        list_event_filter_options(
            db,
            family_id=family_id,
            member_scope_tokens=scope_tokens,
            query=q,
            domain=domain,
            event_type=event_type,
            tag=tag,
            subject_id=subject_id,
            actor_id=actor_id,
            start=start,
            end=end,
        )
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
