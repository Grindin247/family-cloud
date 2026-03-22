from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import raise_api_error
from app.models.profile import RelationshipEdge
from app.schemas.profile import (
    ProfileDetailResponse,
    ProfileFeatureResponse,
    ProfileFeatureUpdate,
    ProfileListResponse,
    ProfileUpdate,
    RelationshipCreate,
    RelationshipListResponse,
    RelationshipResponse,
    RelationshipUpdate,
    ViewerContextResponse,
    ViewerMeResponse,
    ViewerPersonResponse,
)
from app.services.decision_api import (
    ensure_family_access,
    ensure_profile_enabled,
    get_family_context,
    get_family_features,
    get_family_persons,
    get_me,
    update_family_feature,
)
from app.services.profile import (
    build_profile_detail_response,
    build_profile_summary_response,
    create_or_update_profile_record,
    create_relationship_edge,
    delete_relationship_edge,
    list_relationship_edges,
    mutual_default_for_relationship,
    normalize_actor,
    update_relationship_edge,
)

router = APIRouter(prefix="/v1", tags=["profiles"])


def _is_internal_admin(x_internal_admin_token: str | None) -> bool:
    return bool(x_internal_admin_token and x_internal_admin_token == settings.internal_admin_token)


def _caller_email(x_forwarded_user: str | None, x_dev_user: str | None) -> str | None:
    for candidate in (x_forwarded_user, x_dev_user):
        if candidate and candidate.strip():
            return candidate.strip().lower()
    return None


def _ensure_scope(*, family_id: int, actor_email: str | None, internal_admin: bool) -> None:
    ensure_family_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    ensure_profile_enabled(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)


def _ensure_family_access_only(*, family_id: int, actor_email: str | None, internal_admin: bool) -> None:
    ensure_family_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)


def _profile_enabled(*, family_id: int, actor_email: str | None, internal_admin: bool) -> bool:
    features = get_family_features(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    return next((bool(item.get("enabled")) for item in features if item.get("feature_key") == "profile"), False)


def _active_persons(
    *,
    family_id: int,
    actor_email: str | None,
    internal_admin: bool,
) -> list[dict]:
    return [
        item
        for item in get_family_persons(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
        if str(item.get("status") or "active") == "active"
    ]


def _person_map(persons: list[dict]) -> dict[str, dict]:
    return {str(item.get("person_id")): item for item in persons}


def _require_person(persons_by_id: dict[str, dict], person_id: str | UUID) -> dict:
    key = str(person_id)
    person = persons_by_id.get(key)
    if person is None:
        raise_api_error(404, "person_not_found", "person not found for family", {"person_id": key})
    return person


def _relationship_or_404(db: Session, *, family_id: int, relationship_id: UUID) -> RelationshipEdge:
    row = db.get(RelationshipEdge, relationship_id)
    if row is None or row.family_id != family_id:
        raise_api_error(404, "relationship_not_found", "relationship not found", {"family_id": family_id, "relationship_id": str(relationship_id)})
    return row


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
        profile_enabled=_profile_enabled(family_id=family_id, actor_email=actor, internal_admin=internal_admin),
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


@router.put("/families/{family_id}/profile-feature", response_model=ProfileFeatureResponse)
def put_profile_feature(
    family_id: int,
    payload: ProfileFeatureUpdate,
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_family_access_only(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    result = update_family_feature(
        family_id=family_id,
        feature_key="profile",
        enabled=payload.enabled,
        config=payload.config,
        actor_email=actor,
        internal_admin=internal_admin,
    )
    return ProfileFeatureResponse.model_validate(result)


@router.get("/families/{family_id}/profiles", response_model=ProfileListResponse)
def list_profiles(
    family_id: int,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)

    persons = _active_persons(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    relationship_counts: dict[str, int] = {}
    for edge in list_relationship_edges(db, family_id=family_id):
        relationship_counts[edge["source_person_id"]] = relationship_counts.get(edge["source_person_id"], 0) + 1
        relationship_counts[edge["target_person_id"]] = relationship_counts.get(edge["target_person_id"], 0) + 1

    items = [
        build_profile_summary_response(
            db=db,
            family_id=family_id,
            person=person,
            relationship_count=relationship_counts.get(str(person.get("person_id")), 0),
        )
        for person in persons
    ]
    return ProfileListResponse(items=items)


@router.get("/families/{family_id}/profiles/{person_id}", response_model=ProfileDetailResponse)
def get_profile_detail(
    family_id: int,
    person_id: UUID,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)

    persons = _active_persons(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    person = _require_person(_person_map(persons), person_id)
    return build_profile_detail_response(db=db, family_id=family_id, person=person)


@router.put("/families/{family_id}/profiles/{person_id}", response_model=ProfileDetailResponse)
def put_profile_detail(
    family_id: int,
    person_id: UUID,
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)

    persons = _active_persons(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    person = _require_person(_person_map(persons), person_id)
    context = get_family_context(family_id=family_id, actor_email=actor_email) if actor_email else {}
    actor_type, actor_id = normalize_actor(actor_email, internal_admin=internal_admin)

    create_or_update_profile_record(
        db,
        family_id=family_id,
        person_id=person_id,
        payload=payload,
        actor_id=actor_id,
        actor_type=actor_type,
        actor_person_id=str(context.get("actor_person_id")) if context.get("actor_person_id") else None,
        person=person,
    )
    return build_profile_detail_response(db=db, family_id=family_id, person=person)


@router.get("/families/{family_id}/relationships", response_model=RelationshipListResponse)
def get_relationships(
    family_id: int,
    person_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)

    if person_id is not None:
        persons = _active_persons(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
        _require_person(_person_map(persons), person_id)

    return RelationshipListResponse(items=[RelationshipResponse.model_validate(item) for item in list_relationship_edges(db, family_id=family_id, person_id=person_id)])


@router.post("/families/{family_id}/relationships", response_model=RelationshipResponse)
def post_relationship(
    family_id: int,
    payload: RelationshipCreate,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)

    persons = _active_persons(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    persons_by_id = _person_map(persons)
    source_person = _require_person(persons_by_id, payload.source_person_id)
    target_person = _require_person(persons_by_id, payload.target_person_id)
    context = get_family_context(family_id=family_id, actor_email=actor_email) if actor_email else {}
    actor_type, actor_id = normalize_actor(actor_email, internal_admin=internal_admin)

    row = create_relationship_edge(
        db,
        family_id=family_id,
        payload=payload.model_copy(update={"is_mutual": payload.is_mutual if payload.is_mutual is not None else mutual_default_for_relationship(payload.relationship_type)}),
        actor_id=actor_id,
        actor_type=actor_type,
        actor_person_id=str(context.get("actor_person_id")) if context.get("actor_person_id") else None,
        source_person=source_person,
        target_person=target_person,
    )
    return RelationshipResponse.model_validate(row)


@router.put("/families/{family_id}/relationships/{relationship_id}", response_model=RelationshipResponse)
def put_relationship(
    family_id: int,
    relationship_id: UUID,
    payload: RelationshipUpdate,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)

    row = _relationship_or_404(db, family_id=family_id, relationship_id=relationship_id)
    persons = _active_persons(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    persons_by_id = _person_map(persons)
    source_person = _require_person(persons_by_id, payload.source_person_id or row.source_person_id)
    target_person = _require_person(persons_by_id, payload.target_person_id or row.target_person_id)
    context = get_family_context(family_id=family_id, actor_email=actor_email) if actor_email else {}
    actor_type, actor_id = normalize_actor(actor_email, internal_admin=internal_admin)

    updated = update_relationship_edge(
        db,
        row=row,
        payload=payload,
        actor_id=actor_id,
        actor_type=actor_type,
        actor_person_id=str(context.get("actor_person_id")) if context.get("actor_person_id") else None,
        source_person=source_person,
        target_person=target_person,
    )
    return RelationshipResponse.model_validate(updated)


@router.delete("/families/{family_id}/relationships/{relationship_id}", status_code=204)
def remove_relationship(
    family_id: int,
    relationship_id: UUID,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor_email = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)

    row = _relationship_or_404(db, family_id=family_id, relationship_id=relationship_id)
    persons = _active_persons(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    persons_by_id = _person_map(persons)
    source_person = _require_person(persons_by_id, row.source_person_id)
    target_person = _require_person(persons_by_id, row.target_person_id)
    context = get_family_context(family_id=family_id, actor_email=actor_email) if actor_email else {}
    actor_type, actor_id = normalize_actor(actor_email, internal_admin=internal_admin)

    delete_relationship_edge(
        db,
        row=row,
        actor_id=actor_id,
        actor_type=actor_type,
        actor_person_id=str(context.get("actor_person_id")) if context.get("actor_person_id") else None,
        source_person=source_person,
        target_person=target_person,
    )
    return Response(status_code=204)
