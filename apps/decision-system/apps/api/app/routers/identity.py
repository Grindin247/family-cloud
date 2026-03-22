from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.schemas.identity import (
    AliasResolutionResponse,
    FamilyFeatureListResponse,
    FamilyFeatureResponse,
    FamilyFeatureUpdate,
    PersonListResponse,
    PersonResponse,
    ResolvedContextResponse,
    SenderResolutionRequest,
    SenderResolutionResponse,
)
from app.services.access import require_family, require_family_admin, require_family_member
from app.services.identity import (
    build_person_response,
    feature_enabled,
    list_family_persons,
    resolve_person_by_alias,
    resolve_person_by_sender,
    resolve_context,
)
from app.models.identity import FamilyFeature

router = APIRouter(prefix="/v1", tags=["identity"])


def _actor_email(ctx: AuthContext | None, x_dev_user: str | None) -> str | None:
    if ctx is not None:
        return ctx.email
    if x_dev_user:
        return x_dev_user.strip().lower()
    return None


@router.get("/families/{family_id}/persons", response_model=PersonListResponse)
def list_persons(
    family_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family(db, family_id)
    actor = _actor_email(ctx, x_dev_user)
    if actor is not None:
        require_family_member(db, family_id, actor)
    persons = [PersonResponse(**build_person_response(db, person)) for person in list_family_persons(db, family_id)]
    db.commit()
    return PersonListResponse(items=persons)


@router.get("/families/{family_id}/resolve-alias", response_model=AliasResolutionResponse)
def resolve_alias(
    family_id: int,
    q: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family(db, family_id)
    actor = _actor_email(ctx, x_dev_user)
    if actor is not None:
        require_family_member(db, family_id, actor)
    person, source, confidence, matched_alias = resolve_person_by_alias(db, family_id, q)
    return AliasResolutionResponse(
        family_id=family_id,
        query=q,
        person_id=str(person.person_id) if person is not None else None,
        display_name=person.display_name if person is not None else None,
        resolution_source=source,
        confidence=confidence,
        matched_alias=matched_alias,
    )


@router.post("/identity/resolve-sender", response_model=SenderResolutionResponse)
def resolve_sender(
    payload: SenderResolutionRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family(db, payload.family_id)
    actor = _actor_email(ctx, x_dev_user)
    if actor is not None:
        require_family_member(db, payload.family_id, actor)
    person, source, confidence = resolve_person_by_sender(
        db,
        family_id=payload.family_id,
        source_channel=payload.source_channel,
        source_sender_id=payload.source_sender_id,
    )
    return SenderResolutionResponse(
        family_id=payload.family_id,
        source_channel=payload.source_channel,
        source_sender_id=payload.source_sender_id,
        person_id=str(person.person_id) if person is not None else None,
        display_name=person.display_name if person is not None else None,
        resolution_source=source,
        confidence=confidence,
    )


@router.get("/families/{family_id}/context", response_model=ResolvedContextResponse)
def get_resolved_context(
    family_id: int,
    target_person_id: str | None = Query(default=None),
    source_channel: str | None = Query(default=None),
    source_sender_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family(db, family_id)
    actor = _actor_email(ctx, x_dev_user)
    if actor is None:
        raise HTTPException(status_code=401, detail="resolved context requires an authenticated actor")
    require_family_member(db, family_id, actor)
    resolved = resolve_context(
        db,
        family_id=family_id,
        email=actor,
        source_channel=source_channel,
        source_sender_id=source_sender_id,
        target_person_id=target_person_id,
    )
    return ResolvedContextResponse(**resolved.__dict__)


@router.get("/families/{family_id}/features", response_model=FamilyFeatureListResponse)
def list_features(
    family_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family(db, family_id)
    actor = _actor_email(ctx, x_dev_user)
    if actor is not None:
        require_family_member(db, family_id, actor)
    items = []
    for feature_key in ("decision", "tasks", "files", "events", "profile", "health", "education", "finance"):
        enabled = feature_enabled(db, family_id, feature_key)
        row = db.query(FamilyFeature).filter(FamilyFeature.family_id == family_id, FamilyFeature.feature_key == feature_key).one_or_none()
        if row is None:
            continue
        items.append(FamilyFeatureResponse(family_id=family_id, feature_key=feature_key, enabled=enabled, config=row.config_jsonb or {}, updated_at=row.updated_at))
    db.commit()
    return FamilyFeatureListResponse(items=items)


@router.put("/families/{family_id}/features/{feature_key}", response_model=FamilyFeatureResponse)
def update_feature(
    family_id: int,
    feature_key: str,
    payload: FamilyFeatureUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    require_family(db, family_id)
    if ctx is not None:
        require_family_admin(db, family_id, ctx.email)
    row = db.query(FamilyFeature).filter(FamilyFeature.family_id == family_id, FamilyFeature.feature_key == feature_key).one_or_none()
    if row is None:
        row = FamilyFeature(family_id=family_id, feature_key=feature_key, enabled=payload.enabled, config_jsonb=payload.config)
        db.add(row)
    else:
        row.enabled = payload.enabled
        row.config_jsonb = payload.config
    db.commit()
    db.refresh(row)
    return FamilyFeatureResponse(family_id=family_id, feature_key=feature_key, enabled=row.enabled, config=row.config_jsonb or {}, updated_at=row.updated_at)
