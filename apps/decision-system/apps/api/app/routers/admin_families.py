from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.models.entities import Decision, Family, RoadmapItem
from app.services.access import require_family
from app.services.purge import purge_family

router = APIRouter(prefix="/v1/admin/families", tags=["admin"])


def _require_internal_token(x_internal_admin_token: str | None) -> None:
    if not x_internal_admin_token or x_internal_admin_token != settings.internal_admin_token:
        raise HTTPException(status_code=401, detail="invalid internal admin token")


@router.get("")
def list_families_admin(
    db: Session = Depends(get_db),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _require_internal_token(x_internal_admin_token)
    families = db.execute(select(Family).order_by(Family.id.asc())).scalars().all()
    return {"items": [{"id": fam.id, "name": fam.name} for fam in families]}


@router.get("/{family_id}/roadmap_items")
def list_family_roadmap_items_admin(
    family_id: int,
    db: Session = Depends(get_db),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _require_internal_token(x_internal_admin_token)
    require_family(db, family_id)
    rows = db.execute(
        select(RoadmapItem, Decision)
        .join(Decision, Decision.id == RoadmapItem.decision_id)
        .where(Decision.family_id == family_id)
        .order_by(RoadmapItem.id.desc())
    ).all()
    return {
        "items": [
            {
                "id": item.id,
                "decision_id": item.decision_id,
                "bucket": item.bucket,
                "start_date": item.start_date.isoformat() if item.start_date else None,
                "end_date": item.end_date.isoformat() if item.end_date else None,
                "status": item.status,
                "family_id": decision.family_id,
            }
            for item, decision in rows
        ]
    }


@router.delete("/{family_id}", status_code=204)
def delete_family_admin(
    family_id: int,
    db: Session = Depends(get_db),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _require_internal_token(x_internal_admin_token)

    family = require_family(db, family_id)
    purge_family(db, family.id)
    db.commit()
