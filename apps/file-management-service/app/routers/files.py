from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from agents.common.family_events import emit_canonical_event, make_privacy
from agents.common.file_inbox import process_inbox_async
from app.core.config import settings
from app.core.db import get_db
from app.schemas.files import FileIndexRequest, FileIndexResponse, FileSearchRequest, FileSearchResponse, ProcessInboxRequest, ProcessInboxResponse
from app.services.decision_api import ensure_family_access, ensure_files_enabled, get_family_context
from app.services.documents import search_files, upsert_file_document

router = APIRouter(prefix="/v1", tags=["files"])


def _is_internal_admin(x_internal_admin_token: str | None) -> bool:
    return bool(x_internal_admin_token and x_internal_admin_token == settings.internal_admin_token)


def _caller_email(x_forwarded_user: str | None, x_dev_user: str | None) -> str | None:
    for candidate in (x_forwarded_user, x_dev_user):
        if candidate and candidate.strip():
            return candidate.strip().lower()
    return None


@router.post("/files/index", response_model=FileIndexResponse, status_code=201)
def index_file(
    payload: FileIndexRequest,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user) or payload.actor.strip().lower()
    internal_admin = _is_internal_admin(x_internal_admin_token)
    ensure_family_access(family_id=payload.family_id, actor_email=actor, internal_admin=internal_admin)
    ensure_files_enabled(family_id=payload.family_id, actor_email=actor, internal_admin=internal_admin)
    if payload.owner_person_id is None and actor:
        payload.owner_person_id = str(get_family_context(family_id=payload.family_id, actor_email=actor).get("person_id") or "") or None
    payload.actor = actor or payload.actor
    doc = upsert_file_document(db, payload=payload)
    db.commit()
    db.refresh(doc)
    try:
        emit_canonical_event(
            family_id=payload.family_id,
            domain="file",
            event_type="file.indexed",
            actor_id=actor or payload.actor,
            actor_type="system" if internal_admin and not actor else "user",
            subject_type="file",
            subject_id=payload.file_id or payload.path,
            source_agent_id=payload.source_agent_id,
            source_runtime=payload.source_runtime,
            payload={
                "file_id": payload.file_id,
                "path": payload.path,
                "owner_person_id": payload.owner_person_id,
                "title": payload.title,
                "item_type": payload.item_type,
                "role": payload.role,
                "content_type": payload.content_type,
                "media_kind": payload.media_kind,
                "high_level_category": payload.metadata.get("high_level_category") if isinstance(payload.metadata, dict) else None,
                "sentiment": payload.metadata.get("sentiment") if isinstance(payload.metadata, dict) else None,
                "ingestion_status": doc.ingestion_status,
            },
            tags=payload.tags,
            source_session_id=payload.source_session_id,
            privacy=make_privacy(contains_free_text=False),
        )
    except Exception:
        pass
    return FileIndexResponse(
        doc_id=str(doc.doc_id),
        family_id=doc.family_id,
        path=doc.path,
        item_type=doc.item_type,  # type: ignore[arg-type]
        updated_at=doc.updated_at,
        ingestion_status=doc.ingestion_status,
    )


@router.post("/files/search", response_model=FileSearchResponse)
def file_search(
    payload: FileSearchRequest,
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
    return FileSearchResponse(items=search_files(db, payload=payload))


@router.post("/families/{family_id}/files/process-inbox", response_model=ProcessInboxResponse)
async def process_inbox(
    family_id: int,
    payload: ProcessInboxRequest,
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user) or (payload.actor or "").strip().lower()
    internal_admin = _is_internal_admin(x_internal_admin_token)
    ensure_family_access(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    ensure_files_enabled(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    summary = await process_inbox_async(
        mcp_url=settings.nextcloud_mcp_url,
        ready_tag="ready",
        decision_api_base_url=settings.file_self_api_base_url,
        actor=actor,
        family_id=family_id,
        include_dashboard_docs=payload.include_dashboard_docs,
        dashboard_idle_minutes=settings.file_agent_new_doc_idle_minutes if payload.respect_idle_window else 0,
        confidence_threshold=settings.file_agent_autofile_confidence_threshold,
        candidate_mode="closed-inbox",
    )
    return ProcessInboxResponse(**summary)
