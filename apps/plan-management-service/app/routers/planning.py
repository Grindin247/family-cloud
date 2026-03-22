from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import raise_api_error
from app.schemas.planning import (
    GoalOptionListResponse,
    PlanCheckInCreate,
    PlanCreate,
    PlanInstanceListResponse,
    PlanListResponse,
    PlanPreviewResponse,
    PlanResponse,
    PlanUpdate,
    PlanningFeatureResponse,
    PlanningFeatureUpdate,
    ViewerContextResponse,
    ViewerMeResponse,
    ViewerPersonResponse,
)
from app.services.decision_api import (
    ensure_family_access,
    ensure_planning_enabled,
    get_family_context,
    get_family_features,
    get_family_persons,
    get_me,
    list_goals,
    update_family_feature,
)
from app.services.planning import (
    PlanContext,
    _plan_or_404,
    _instance_responses,
    activate_plan,
    archive_plan,
    build_plan_response,
    create_plan,
    list_goal_options,
    list_plans,
    normalize_actor,
    pause_plan,
    preview_plan,
    record_checkin,
    reconcile_plan_instances,
    update_plan,
)

router = APIRouter(prefix="/v1", tags=["planning"])


def _is_internal_admin(x_internal_admin_token: str | None) -> bool:
    return bool(x_internal_admin_token and x_internal_admin_token == settings.internal_admin_token)


def _caller_email(x_forwarded_user: str | None, x_dev_user: str | None) -> str | None:
    for candidate in (x_forwarded_user, x_dev_user):
        if candidate and candidate.strip():
            return candidate.strip().lower()
    return None


def _ensure_scope(*, family_id: int, actor_email: str | None, internal_admin: bool) -> None:
    ensure_family_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    ensure_planning_enabled(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)


def _ensure_family_access_only(*, family_id: int, actor_email: str | None, internal_admin: bool) -> None:
    ensure_family_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)


def _planning_enabled(*, family_id: int, actor_email: str | None, internal_admin: bool) -> bool:
    features = get_family_features(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    return next((bool(item.get("enabled")) for item in features if item.get("feature_key") == "planning"), False)


def _active_persons(*, family_id: int, actor_email: str | None, internal_admin: bool) -> list[dict]:
    return [
        item
        for item in get_family_persons(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
        if str(item.get("status") or "active") == "active"
    ]


def _person_map(persons: list[dict]) -> dict[str, dict]:
    return {str(item.get("person_id")): item for item in persons}


def _plan_context(*, actor_email: str | None, internal_admin: bool, actor_person_id: str | None) -> PlanContext:
    actor_type, actor_id = normalize_actor(actor_email, internal_admin=internal_admin)
    return PlanContext(
        actor_id=actor_id,
        actor_type=actor_type,
        actor_person_id=actor_person_id,
        actor_email=actor_email,
        internal_admin=internal_admin,
    )


@router.get("/me", response_model=ViewerMeResponse)
def viewer_me(
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    return ViewerMeResponse.model_validate(get_me(actor_email=actor))


@router.get("/families/{family_id}/viewer-context", response_model=ViewerContextResponse)
def viewer_context(
    family_id: int,
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_family_access_only(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    context = get_family_context(family_id=family_id, actor_email=actor)
    persons = _active_persons(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    return ViewerContextResponse(
        family_id=family_id,
        family_slug=str(context.get("family_slug") or ""),
        person_id=str(context.get("person_id") or ""),
        actor_person_id=str(context.get("actor_person_id") or context.get("person_id") or ""),
        target_person_id=str(context.get("target_person_id") or context.get("person_id") or ""),
        is_family_admin=bool(context.get("is_family_admin")),
        planning_enabled=_planning_enabled(family_id=family_id, actor_email=actor, internal_admin=internal_admin),
        primary_email=context.get("primary_email"),
        directory_account_id=context.get("directory_account_id"),
        member_id=context.get("member_id"),
        persons=[
            ViewerPersonResponse(
                person_id=str(item.get("person_id")),
                display_name=str(item.get("display_name") or item.get("canonical_name") or item.get("person_id")),
                role_in_family=item.get("role_in_family"),
                is_admin=bool(item.get("is_admin")),
                status=str(item.get("status") or "active"),
                accounts=item.get("accounts") if isinstance(item.get("accounts"), dict) else {},
            )
            for item in persons
        ],
    )


@router.put("/families/{family_id}/planning-feature", response_model=PlanningFeatureResponse)
def put_planning_feature(
    family_id: int,
    payload: PlanningFeatureUpdate,
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_family_access_only(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    result = update_family_feature(
        family_id=family_id,
        feature_key="planning",
        enabled=payload.enabled,
        config=payload.config,
        actor_email=actor,
        internal_admin=internal_admin,
    )
    return PlanningFeatureResponse.model_validate(result)


@router.get("/families/{family_id}/plans/goal-options", response_model=GoalOptionListResponse)
def goal_options(
    family_id: int,
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    return GoalOptionListResponse(items=list_goal_options(goals=list_goals(family_id=family_id, actor_email=actor, internal_admin=internal_admin)))


@router.get("/families/{family_id}/plans", response_model=PlanListResponse)
def list_family_plans(
    family_id: int,
    status: str | None = Query(default=None),
    owner_scope: str | None = Query(default=None),
    owner_person_id: str | None = Query(default=None),
    plan_kind: str | None = Query(default=None),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    context = get_family_context(family_id=family_id, actor_email=actor_email) if actor_email else {}
    plan_context = _plan_context(actor_email=actor_email, internal_admin=internal_admin, actor_person_id=str(context.get("actor_person_id")) if context.get("actor_person_id") else None)
    items = list_plans(db, family_id=family_id, status=status, owner_scope=owner_scope, owner_person_id=owner_person_id, plan_kind=plan_kind)
    responses: list[PlanResponse] = []
    for row in items:
        reconcile_plan_instances(db, row=row, context=plan_context)
        responses.append(build_plan_response(db, row=row))
    return PlanListResponse(items=responses)


@router.post("/families/{family_id}/plans", response_model=PlanResponse, status_code=201)
def create_family_plan(
    family_id: int,
    payload: PlanCreate,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    persons = _active_persons(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    context = get_family_context(family_id=family_id, actor_email=actor_email) if actor_email else {}
    row = create_plan(
        db,
        family_id=family_id,
        payload=payload,
        context=_plan_context(actor_email=actor_email, internal_admin=internal_admin, actor_person_id=str(context.get("actor_person_id")) if context.get("actor_person_id") else None),
        persons_by_id=_person_map(persons),
    )
    return build_plan_response(db, row=row)


@router.get("/families/{family_id}/plans/{plan_id}", response_model=PlanResponse)
def get_plan_detail(
    family_id: int,
    plan_id: UUID,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    row = _plan_or_404(db, family_id=family_id, plan_id=plan_id)
    context = get_family_context(family_id=family_id, actor_email=actor_email) if actor_email else {}
    reconcile_plan_instances(
        db,
        row=row,
        context=_plan_context(actor_email=actor_email, internal_admin=internal_admin, actor_person_id=str(context.get("actor_person_id")) if context.get("actor_person_id") else None),
    )
    return build_plan_response(db, row=row)


@router.put("/families/{family_id}/plans/{plan_id}", response_model=PlanResponse)
def put_plan_detail(
    family_id: int,
    plan_id: UUID,
    payload: PlanUpdate,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    persons = _active_persons(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    context = get_family_context(family_id=family_id, actor_email=actor_email) if actor_email else {}
    row = update_plan(
        db,
        row=_plan_or_404(db, family_id=family_id, plan_id=plan_id),
        payload=payload,
        context=_plan_context(actor_email=actor_email, internal_admin=internal_admin, actor_person_id=str(context.get("actor_person_id")) if context.get("actor_person_id") else None),
        persons_by_id=_person_map(persons),
    )
    return build_plan_response(db, row=row)


@router.post("/families/{family_id}/plans/{plan_id}/activate", response_model=PlanResponse)
def activate_family_plan(
    family_id: int,
    plan_id: UUID,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    context = get_family_context(family_id=family_id, actor_email=actor_email) if actor_email else {}
    row = activate_plan(
        db,
        row=_plan_or_404(db, family_id=family_id, plan_id=plan_id),
        context=_plan_context(actor_email=actor_email, internal_admin=internal_admin, actor_person_id=str(context.get("actor_person_id")) if context.get("actor_person_id") else None),
    )
    return build_plan_response(db, row=row)


@router.post("/families/{family_id}/plans/{plan_id}/pause", response_model=PlanResponse)
def pause_family_plan(
    family_id: int,
    plan_id: UUID,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    context = get_family_context(family_id=family_id, actor_email=actor_email) if actor_email else {}
    row = pause_plan(
        db,
        row=_plan_or_404(db, family_id=family_id, plan_id=plan_id),
        context=_plan_context(actor_email=actor_email, internal_admin=internal_admin, actor_person_id=str(context.get("actor_person_id")) if context.get("actor_person_id") else None),
    )
    return build_plan_response(db, row=row)


@router.post("/families/{family_id}/plans/{plan_id}/archive", response_model=PlanResponse)
def archive_family_plan(
    family_id: int,
    plan_id: UUID,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    context = get_family_context(family_id=family_id, actor_email=actor_email) if actor_email else {}
    row = archive_plan(
        db,
        row=_plan_or_404(db, family_id=family_id, plan_id=plan_id),
        context=_plan_context(actor_email=actor_email, internal_admin=internal_admin, actor_person_id=str(context.get("actor_person_id")) if context.get("actor_person_id") else None),
    )
    return build_plan_response(db, row=row)


@router.get("/families/{family_id}/plans/{plan_id}/preview", response_model=PlanPreviewResponse)
def preview_family_plan(
    family_id: int,
    plan_id: UUID,
    days: int = Query(default=14, ge=1, le=31),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    return preview_plan(db, row=_plan_or_404(db, family_id=family_id, plan_id=plan_id), days=days)


@router.get("/families/{family_id}/plans/{plan_id}/instances", response_model=PlanInstanceListResponse)
def list_plan_instances(
    family_id: int,
    plan_id: UUID,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    row = _plan_or_404(db, family_id=family_id, plan_id=plan_id)
    context = get_family_context(family_id=family_id, actor_email=actor_email) if actor_email else {}
    reconcile_plan_instances(
        db,
        row=row,
        context=_plan_context(actor_email=actor_email, internal_admin=internal_admin, actor_person_id=str(context.get("actor_person_id")) if context.get("actor_person_id") else None),
    )
    return PlanInstanceListResponse(items=_instance_responses(db, plan_id=row.plan_id))


@router.post("/families/{family_id}/plans/{plan_id}/checkins", response_model=PlanResponse)
def create_plan_checkin(
    family_id: int,
    plan_id: UUID,
    payload: PlanCheckInCreate,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    context = get_family_context(family_id=family_id, actor_email=actor_email) if actor_email else {}
    row = _plan_or_404(db, family_id=family_id, plan_id=plan_id)
    record_checkin(
        db,
        row=row,
        payload=payload,
        context=_plan_context(actor_email=actor_email, internal_admin=internal_admin, actor_person_id=str(context.get("actor_person_id")) if context.get("actor_person_id") else None),
    )
    return build_plan_response(db, row=row)
