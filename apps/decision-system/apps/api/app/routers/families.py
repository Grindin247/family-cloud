from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.models.entities import Family, FamilyMember, RoleEnum
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
from app.services.purge import purge_family

router = APIRouter(prefix="/v1/families", tags=["families"])


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
    family = Family(name=payload.name)
    db.add(family)
    db.flush()
    if ctx is not None:
        # Creator becomes the initial admin member.
        db.add(
            FamilyMember(
                family_id=family.id,
                email=ctx.email,
                display_name=ctx.email,
                role=RoleEnum.admin,
            )
        )
    db.commit()
    db.refresh(family)
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
    family.name = payload.name
    db.commit()
    db.refresh(family)
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
    purge_family(db, family.id)
    db.commit()


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
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="email already exists") from None

    db.refresh(member)
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

    if payload.display_name is not None:
        member.display_name = payload.display_name
    if payload.role is not None:
        member.role = RoleEnum(payload.role)

    db.commit()
    db.refresh(member)
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

    db.delete(member)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Deleting a member can fail if they are referenced by decisions, budgets, etc.
        # Avoid a 500; clients can delete the family (which purges dependents) instead.
        raise HTTPException(
            status_code=409,
            detail="cannot delete member with dependent records; delete family or purge dependent records first",
        ) from None
