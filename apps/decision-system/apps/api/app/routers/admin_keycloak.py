from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.services.keycloak_sync import sync_keycloak_families

router = APIRouter(prefix="/v1/admin/keycloak", tags=["admin"])


@router.post("/sync")
async def sync(
    db: Session = Depends(get_db),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    if not x_internal_admin_token or x_internal_admin_token != settings.internal_admin_token:
        raise HTTPException(status_code=401, detail="invalid internal admin token")

    try:
        stats = await sync_keycloak_families(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "families_created": stats.families_created,
        "families_updated": stats.families_updated,
        "members_created": stats.members_created,
        "members_updated": stats.members_updated,
        "members_deleted": stats.members_deleted,
    }

