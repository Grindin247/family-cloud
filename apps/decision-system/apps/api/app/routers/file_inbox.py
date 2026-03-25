from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from agents.common.file_inbox import process_inbox_async
from app.core.auth import AuthContext, get_auth_context
from app.core.config import settings
from app.core.db import get_db
from app.schemas.files import ProcessInboxRequest, ProcessInboxResponse
from app.services.access import require_family, require_family_feature, require_family_member
from app.services.file_service_proxy import file_api_enabled, file_proxy_headers, proxy_file_request

router = APIRouter(prefix="/v1/family/{family_id}/files", tags=["file-inbox"])


def _caller_email(ctx: AuthContext | None, x_dev_user: str | None, payload_actor: str | None) -> str:
    if ctx is not None:
        return ctx.email
    if x_dev_user:
        return x_dev_user.strip().lower()
    if payload_actor:
        return payload_actor.strip().lower()
    raise HTTPException(status_code=401, detail="missing actor for inbox processing")


@router.post("/process-inbox", response_model=ProcessInboxResponse)
async def process_inbox(
    family_id: int,
    payload: ProcessInboxRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    if file_api_enabled():
        return proxy_file_request(
            "POST",
            f"/families/{family_id}/files/process-inbox",
            headers=file_proxy_headers(ctx=ctx, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token),
            json_body=payload.model_dump(mode="json", exclude_none=True),
        )
    require_family(db, family_id)
    require_family_feature(db, family_id, "files")
    actor = _caller_email(ctx, x_dev_user, payload.actor)
    require_family_member(db, family_id, actor)
    try:
        summary = await process_inbox_async(
            mcp_url=settings.nextcloud_mcp_url,
            ready_tag="ready",
            decision_api_base_url=settings.decision_self_api_base_url,
            actor=actor,
            family_id=family_id,
            include_dashboard_docs=payload.include_dashboard_docs,
            dashboard_idle_minutes=settings.file_agent_new_doc_idle_minutes if payload.respect_idle_window else 0,
            confidence_threshold=settings.file_agent_autofile_confidence_threshold,
            candidate_mode="closed-inbox",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ProcessInboxResponse(**summary)
