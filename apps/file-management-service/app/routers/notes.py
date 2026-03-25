from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from agents.common.family_events import emit_canonical_event, make_privacy
from app.core.config import settings
from app.core.db import get_db
from app.schemas.notes import NoteIndexRequest, NoteIndexResponse, NoteSearchRequest, NoteSearchResponse
from app.services.decision_api import ensure_family_access, ensure_files_enabled, get_family_context
from app.services.documents import search_notes, upsert_note_document

router = APIRouter(prefix="/v1", tags=["notes"])


def _is_internal_admin(x_internal_admin_token: str | None) -> bool:
    return bool(x_internal_admin_token and x_internal_admin_token == settings.internal_admin_token)


def _caller_email(x_forwarded_user: str | None, x_dev_user: str | None) -> str | None:
    for candidate in (x_forwarded_user, x_dev_user):
        if candidate and candidate.strip():
            return candidate.strip().lower()
    return None


@router.post("/notes/index", response_model=NoteIndexResponse, status_code=201)
def index_note(
    payload: NoteIndexRequest,
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
    doc = upsert_note_document(db, payload=payload)
    db.commit()
    db.refresh(doc)
    try:
        emit_canonical_event(
            family_id=payload.family_id,
            domain="note",
            event_type="note.created",
            actor_id=actor or payload.actor,
            actor_type="system" if internal_admin and not actor else "user",
            subject_type="note",
            subject_id=payload.path,
            source_agent_id=payload.source_agent_id,
            source_runtime=payload.source_runtime,
            payload={
                "path": payload.path,
                "owner_person_id": payload.owner_person_id,
                "title": payload.title,
                "note_type": payload.metadata.get("note_type") if isinstance(payload.metadata, dict) else None,
                "content_type": payload.content_type,
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
    return NoteIndexResponse(
        doc_id=str(doc.doc_id),
        family_id=doc.family_id,
        path=doc.path,
        item_type=doc.item_type,  # type: ignore[arg-type]
        updated_at=doc.updated_at,
        ingestion_status=doc.ingestion_status,
    )


@router.post("/notes/search", response_model=NoteSearchResponse)
def note_search(
    payload: NoteSearchRequest,
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
    return NoteSearchResponse(items=search_notes(db, payload=payload))
