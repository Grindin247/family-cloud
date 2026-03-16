from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Family, FamilyMember, RoleEnum


def get_member_by_email(db: Session, family_id: int, email: str) -> FamilyMember | None:
    return db.execute(
        select(FamilyMember).where(FamilyMember.family_id == family_id, FamilyMember.email == email)
    ).scalar_one_or_none()


def require_family(db: Session, family_id: int) -> Family:
    family = db.get(Family, family_id)
    if family is None:
        raise HTTPException(status_code=404, detail="family not found")
    return family


def require_family_member(db: Session, family_id: int, email: str) -> FamilyMember:
    member = get_member_by_email(db, family_id, email)
    if member is None:
        raise HTTPException(status_code=403, detail="not a member of this family")
    return member


def require_family_admin(db: Session, family_id: int, email: str) -> FamilyMember:
    member = require_family_member(db, family_id, email)
    if member.role != RoleEnum.admin:
        family_has_admin = db.execute(
            select(FamilyMember.id).where(
                FamilyMember.family_id == family_id,
                FamilyMember.role == RoleEnum.admin,
            )
        ).first()
        if family_has_admin is None and member.role == RoleEnum.editor:
            return member
        raise HTTPException(status_code=403, detail="admin role required")
    return member


def require_family_editor(db: Session, family_id: int, email: str) -> FamilyMember:
    member = require_family_member(db, family_id, email)
    if member.role not in (RoleEnum.admin, RoleEnum.editor):
        raise HTTPException(status_code=403, detail="editor role required")
    return member
