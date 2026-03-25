from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.schemas.jobs import FollowupJobRequest, FollowupJobResponse
from app.services.decision_api import ensure_family_access, ensure_files_enabled
from app.services.jobs import enqueue_job

router = APIRouter(prefix="/v1", tags=["jobs"])


def _is_internal_admin(x_internal_admin_token: str | None) -> bool:
    return bool(x_internal_admin_token and x_internal_admin_token == settings.internal_admin_token)


def _caller_email(x_forwarded_user: str | None, x_dev_user: str | None) -> str | None:
    for candidate in (x_forwarded_user, x_dev_user):
        if candidate and candidate.strip():
            return candidate.strip().lower()
    return None


@router.post("/families/{family_id}/jobs/followups", response_model=FollowupJobResponse, status_code=201)
def create_followup_job(
    family_id: int,
    payload: FollowupJobRequest,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user) or payload.actor.strip().lower()
    internal_admin = _is_internal_admin(x_internal_admin_token)
    ensure_family_access(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    ensure_files_enabled(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    job = enqueue_job(
        db,
        family_id=family_id,
        job_type=payload.job_type,
        actor=actor or payload.actor,
        dedupe_key=payload.dedupe_key,
        payload=payload.payload,
    )
    db.commit()
    db.refresh(job)
    return FollowupJobResponse(job_id=str(job.job_id), family_id=job.family_id, job_type=job.job_type, status=job.status)
