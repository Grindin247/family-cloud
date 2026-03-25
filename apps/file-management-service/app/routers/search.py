from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.schemas.search import UnifiedSearchRequest, UnifiedSearchResponse
from app.services.decision_api import ensure_family_access, ensure_files_enabled, get_family_context
from app.services.documents import search_all

router = APIRouter(prefix="/v1", tags=["search"])


def _is_internal_admin(x_internal_admin_token: str | None) -> bool:
    return bool(x_internal_admin_token and x_internal_admin_token == settings.internal_admin_token)


def _caller_email(x_forwarded_user: str | None, x_dev_user: str | None) -> str | None:
    for candidate in (x_forwarded_user, x_dev_user):
        if candidate and candidate.strip():
            return candidate.strip().lower()
    return None


@router.post("/search", response_model=UnifiedSearchResponse)
def unified_search(
    payload: UnifiedSearchRequest,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user) or payload.actor.strip().lower()
    internal_admin = _is_internal_admin(x_internal_admin_token)
    ensure_family_access(family_id=payload.family_id, actor_email=actor, internal_admin=internal_admin)
    ensure_files_enabled(family_id=payload.family_id, actor_email=actor, internal_admin=internal_admin)
    payload.actor = actor or payload.actor
    return UnifiedSearchResponse(items=search_all(db, payload=payload))
