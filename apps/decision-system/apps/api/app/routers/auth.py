from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, get_auth_context, require_auth
from app.core.db import get_db
from app.models.entities import Family, FamilyMember

router = APIRouter(prefix="/v1", tags=["auth"])


@router.get("/me")
def get_me(
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    """
    Returns the authenticated user's email and family memberships.

    If auth is disabled (AUTH_MODE=none), this returns an anonymous response so dev/test flows still work.
    """
    if ctx is None:
        return {"authenticated": False, "email": None, "memberships": []}

    memberships = db.execute(
        select(FamilyMember, Family)
        .join(Family, Family.id == FamilyMember.family_id)
        .where(FamilyMember.email == ctx.email)
        .order_by(Family.id.asc())
    ).all()

    return {
        "authenticated": True,
        "email": ctx.email,
        "memberships": [
            {
                "family_id": family.id,
                "family_name": family.name,
                "member_id": member.id,
                "role": member.role.value,
            }
            for member, family in memberships
        ],
    }


@router.post("/logout")
def logout(_: AuthContext = Depends(require_auth)):
    # With forward-auth, logout is handled by the IdP/proxy; the app doesn't hold a session.
    return {"ok": True}

