from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from agents.common.family_events import emit_canonical_event, make_privacy
from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.schemas.files import FileIndexRequest, FileIndexResponse, FileSearchRequest, FileSearchResponse
from app.services.access import require_family, require_family_member
from app.services.files import search_files, upsert_file_document

router = APIRouter(prefix="/v1/files", tags=["files"])


@router.post("/index", response_model=FileIndexResponse, status_code=201)
def index_file(
    payload: FileIndexRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family(db, payload.family_id)
    caller = (ctx.email if ctx is not None else (x_dev_user or payload.actor)).strip().lower()
    require_family_member(db, payload.family_id, caller)
    doc = upsert_file_document(db, payload=payload)
    db.commit()
    db.refresh(doc)
    try:
        emit_canonical_event(
            family_id=payload.family_id,
            domain="file",
            event_type="file.indexed",
            actor_id=caller,
            actor_type="user",
            subject_type="file",
            subject_id=payload.file_id or payload.path,
            source_agent_id="FileAgent",
            source_runtime="backend",
            payload={
                "file_id": payload.file_id,
                "path": payload.path,
                "title": payload.title,
                "item_type": payload.item_type,
                "role": payload.role,
                "content_type": payload.content_type,
                "media_kind": payload.media_kind,
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
    )


@router.post("/search", response_model=FileSearchResponse)
def file_search(
    payload: FileSearchRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family(db, payload.family_id)
    caller = (ctx.email if ctx is not None else (x_dev_user or payload.actor)).strip().lower()
    require_family_member(db, payload.family_id, caller)
    return FileSearchResponse(items=search_files(db, payload=payload))
