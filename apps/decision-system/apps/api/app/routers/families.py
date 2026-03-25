from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.models.entities import Family, FamilyMember, RoleEnum
from app.models.identity import Person
from app.schemas.families import (
    FamilyCreate,
    FamilyListResponse,
    FamilyMemberCreate,
    FamilyMemberListResponse,
    FamilyMemberResponse,
    FamilyMemberUpdate,
    FamilyResponse,
    FamilyUpdate,
)
from app.services.access import require_family, require_family_admin, require_family_member
from app.services.family_events import make_backend_event_payload
from app.services.identity import ensure_person_for_member, slugify_family_name
from app.services.purge import purge_family
from agents.common.family_events import diff_field_paths, make_privacy, publish_event as publish_family_event, snippet_fields

router = APIRouter(prefix="/v1/families", tags=["families"])


def _actor_id(ctx: AuthContext | None) -> str:
    return ctx.email if ctx is not None else "system"


def _emit_family_event(*, family_id: int, actor_id: str, event_type: str, subject_id: str, subject_type: str, payload: dict, subject_person_id: str | None = None, tags: list[str] | None = None) -> None:
    event = make_backend_event_payload(
        family_id=family_id,
        domain="family",
        event_type=event_type,
        actor_id=actor_id,
        actor_type="system" if actor_id == "system" else "user",
        subject_id=subject_id,
        subject_type=subject_type,
        subject_person_id=subject_person_id,
        payload=payload,
        source_agent_id="FamilyService",
        source_runtime="backend",
        tags=tags or ["family"],
        privacy=make_privacy(
            contains_pii=bool(subject_person_id),
            contains_child_data=bool(subject_person_id),
            contains_free_text=any(key.endswith("_snippet") for key in payload),
        ),
    )
    publish_family_event(event)


@router.get("", response_model=FamilyListResponse)
def list_families(
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    query = select(Family)
    if ctx is not None:
        query = query.join(FamilyMember, FamilyMember.family_id == Family.id).where(FamilyMember.email == ctx.email)
    families = db.execute(query.order_by(Family.id.asc())).scalars().all()
    return FamilyListResponse(items=[FamilyResponse.model_validate(item, from_attributes=True) for item in families])


@router.post("", response_model=FamilyResponse, status_code=201)
def create_family(
    payload: FamilyCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    family = Family(name=payload.name, slug=slugify_family_name(payload.name))
    db.add(family)
    db.flush()
    if ctx is not None:
        # Creator becomes the initial admin member.
        member = FamilyMember(
            family_id=family.id,
            email=ctx.email,
            display_name=ctx.email,
            role=RoleEnum.admin,
        )
        db.add(member)
        db.flush()
        ensure_person_for_member(db, member)
    db.commit()
    db.refresh(family)
    try:
        payload = {"family_id": family.id, "slug": family.slug}
        payload.update(snippet_fields("family_name", family.name))
        payload["title"] = payload.get("family_name_snippet") or f"Family {family.id}"
        _emit_family_event(
            family_id=family.id,
            actor_id=_actor_id(ctx),
            event_type="family.created",
            subject_id=str(family.id),
            subject_type="family",
            payload=payload,
        )
        if ctx is not None:
            member = db.execute(select(FamilyMember).where(FamilyMember.family_id == family.id, FamilyMember.email == ctx.email)).scalar_one_or_none()
            person = db.query(Person).filter(Person.legacy_member_id == member.id).one_or_none() if member is not None else None
            if member is not None:
                member_payload = {
                    "family_id": family.id,
                    "member_id": member.id,
                    "role": member.role.value,
                    "person_id": str(person.person_id) if person is not None else None,
                }
                member_payload.update(snippet_fields("display_name", member.display_name))
                member_payload["title"] = member_payload.get("display_name_snippet") or member.email
                _emit_family_event(
                    family_id=family.id,
                    actor_id=_actor_id(ctx),
                    event_type="family_member.created",
                    subject_id=str(member.id),
                    subject_type="family_member",
                    subject_person_id=str(person.person_id) if person is not None else None,
                    payload=member_payload,
                    tags=["family", "member"],
                )
    except Exception:
        pass
    return FamilyResponse.model_validate(family, from_attributes=True)


@router.get("/{family_id}", response_model=FamilyResponse)
def get_family(
    family_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    family = require_family(db, family_id)
    if ctx is not None:
        require_family_member(db, family_id, ctx.email)
    return FamilyResponse.model_validate(family, from_attributes=True)


@router.patch("/{family_id}", response_model=FamilyResponse)
def update_family(
    family_id: int,
    payload: FamilyUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    family = require_family(db, family_id)
    if ctx is not None:
        require_family_admin(db, family_id, ctx.email)
    before_state = {"name": family.name, "slug": family.slug}
    family.name = payload.name
    family.slug = slugify_family_name(payload.name)
    db.commit()
    db.refresh(family)
    try:
        event_payload = {"family_id": family.id, "slug": family.slug, "changed_fields": diff_field_paths(before_state, {"name": family.name, "slug": family.slug})}
        event_payload.update(snippet_fields("family_name", family.name))
        event_payload["title"] = event_payload.get("family_name_snippet") or f"Family {family.id}"
        _emit_family_event(
            family_id=family.id,
            actor_id=_actor_id(ctx),
            event_type="family.updated",
            subject_id=str(family.id),
            subject_type="family",
            payload=event_payload,
        )
    except Exception:
        pass
    return FamilyResponse.model_validate(family, from_attributes=True)


@router.delete("/{family_id}", status_code=204)
def delete_family(
    family_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    family = require_family(db, family_id)
    if ctx is not None:
        require_family_admin(db, family_id, ctx.email)
    payload = {"family_id": family.id, "slug": family.slug}
    payload.update(snippet_fields("family_name", family.name))
    payload["title"] = payload.get("family_name_snippet") or f"Family {family.id}"
    purge_family(db, family.id)
    db.commit()
    try:
        _emit_family_event(
            family_id=family.id,
            actor_id=_actor_id(ctx),
            event_type="family.deleted",
            subject_id=str(family.id),
            subject_type="family",
            payload=payload,
        )
    except Exception:
        pass


@router.get("/{family_id}/members", response_model=FamilyMemberListResponse)
def list_family_members(
    family_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    require_family(db, family_id)
    if ctx is not None:
        require_family_member(db, family_id, ctx.email)

    members = db.execute(
        select(FamilyMember).where(FamilyMember.family_id == family_id).order_by(FamilyMember.id.asc())
    ).scalars().all()
    return FamilyMemberListResponse(
        items=[
            FamilyMemberResponse(
                id=item.id,
                family_id=item.family_id,
                email=item.email,
                display_name=item.display_name,
                role=item.role.value,
            )
            for item in members
        ]
    )


@router.post("/{family_id}/members", response_model=FamilyMemberResponse, status_code=201)
def create_family_member(
    family_id: int,
    payload: FamilyMemberCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    require_family(db, family_id)
    if ctx is not None:
        require_family_admin(db, family_id, ctx.email)

    member = FamilyMember(
        family_id=family_id,
        email=str(payload.email).lower(),
        display_name=payload.display_name,
        role=RoleEnum(payload.role),
    )
    db.add(member)
    try:
        db.flush()
        ensure_person_for_member(db, member)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="email already exists") from None

    db.refresh(member)
    person = db.query(Person).filter(Person.legacy_member_id == member.id).one_or_none()
    try:
        payload = {
            "family_id": family_id,
            "member_id": member.id,
            "role": member.role.value,
            "person_id": str(person.person_id) if person is not None else None,
        }
        payload.update(snippet_fields("display_name", member.display_name))
        payload["title"] = payload.get("display_name_snippet") or member.email
        _emit_family_event(
            family_id=family_id,
            actor_id=_actor_id(ctx),
            event_type="family_member.created",
            subject_id=str(member.id),
            subject_type="family_member",
            subject_person_id=str(person.person_id) if person is not None else None,
            payload=payload,
            tags=["family", "member"],
        )
    except Exception:
        pass
    return FamilyMemberResponse(
        id=member.id,
        family_id=member.family_id,
        email=member.email,
        display_name=member.display_name,
        role=member.role.value,
    )


@router.get("/{family_id}/members/{member_id}", response_model=FamilyMemberResponse)
def get_family_member(
    family_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    require_family(db, family_id)
    if ctx is not None:
        require_family_member(db, family_id, ctx.email)
    member = db.get(FamilyMember, member_id)
    if member is None or member.family_id != family_id:
        raise HTTPException(status_code=404, detail="family member not found")

    return FamilyMemberResponse(
        id=member.id,
        family_id=member.family_id,
        email=member.email,
        display_name=member.display_name,
        role=member.role.value,
    )


@router.patch("/{family_id}/members/{member_id}", response_model=FamilyMemberResponse)
def update_family_member(
    family_id: int,
    member_id: int,
    payload: FamilyMemberUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    require_family(db, family_id)
    if ctx is not None:
        require_family_admin(db, family_id, ctx.email)
    member = db.get(FamilyMember, member_id)
    if member is None or member.family_id != family_id:
        raise HTTPException(status_code=404, detail="family member not found")

    before_state = {"display_name": member.display_name, "role": member.role.value}
    if payload.display_name is not None:
        member.display_name = payload.display_name
    if payload.role is not None:
        member.role = RoleEnum(payload.role)

    ensure_person_for_member(db, member)
    db.commit()
    db.refresh(member)
    person = db.query(Person).filter(Person.legacy_member_id == member.id).one_or_none()
    try:
        event_payload = {
            "family_id": family_id,
            "member_id": member.id,
            "role": member.role.value,
            "person_id": str(person.person_id) if person is not None else None,
            "changed_fields": diff_field_paths(before_state, {"display_name": member.display_name, "role": member.role.value}),
        }
        event_payload.update(snippet_fields("display_name", member.display_name))
        event_payload["title"] = event_payload.get("display_name_snippet") or member.email
        _emit_family_event(
            family_id=family_id,
            actor_id=_actor_id(ctx),
            event_type="family_member.updated",
            subject_id=str(member.id),
            subject_type="family_member",
            subject_person_id=str(person.person_id) if person is not None else None,
            payload=event_payload,
            tags=["family", "member"],
        )
    except Exception:
        pass
    return FamilyMemberResponse(
        id=member.id,
        family_id=member.family_id,
        email=member.email,
        display_name=member.display_name,
        role=member.role.value,
    )


@router.delete("/{family_id}/members/{member_id}", status_code=204)
def delete_family_member(
    family_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    require_family(db, family_id)
    if ctx is not None:
        require_family_admin(db, family_id, ctx.email)
    member = db.get(FamilyMember, member_id)
    if member is None or member.family_id != family_id:
        raise HTTPException(status_code=404, detail="family member not found")

    person = db.query(Person).filter(Person.legacy_member_id == member.id).one_or_none()
    payload = {
        "family_id": family_id,
        "member_id": member.id,
        "role": member.role.value,
        "person_id": str(person.person_id) if person is not None else None,
    }
    payload.update(snippet_fields("display_name", member.display_name))
    payload["title"] = payload.get("display_name_snippet") or member.email
    if person is not None:
        person.legacy_member_id = None
        person.status = "active"
    db.delete(member)
    try:
        db.commit()
        try:
            _emit_family_event(
                family_id=family_id,
                actor_id=_actor_id(ctx),
                event_type="family_member.deleted",
                subject_id=str(member.id),
                subject_type="family_member",
                subject_person_id=str(person.person_id) if person is not None else None,
                payload=payload,
                tags=["family", "member"],
            )
        except Exception:
            pass
    except IntegrityError:
        db.rollback()
        # Deleting a member can fail if they are referenced by decisions, budgets, etc.
        # Avoid a 500; clients can delete the family (which purges dependents) instead.
        raise HTTPException(
            status_code=409,
            detail="cannot delete member with dependent records; delete family or purge dependent records first",
        ) from None
