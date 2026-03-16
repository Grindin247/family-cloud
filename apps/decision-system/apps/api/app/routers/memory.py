from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.schemas.memory import (
    MemoryDocumentCreate,
    MemoryDocumentResponse,
    MemorySearchRequest,
    MemorySearchResponse,
)
from app.services.access import require_family, require_family_member
from app.services.memory import create_document_with_embeddings, semantic_search

router = APIRouter(prefix="/v1/family/{family_id}/memory", tags=["memory"])


@router.post("/documents", response_model=MemoryDocumentResponse, status_code=201)
def create_memory_document(
    family_id: int,
    payload: MemoryDocumentCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family(db, family_id)
    if ctx is not None:
        require_family_member(db, family_id, ctx.email)
    doc = create_document_with_embeddings(
        db,
        family_id=family_id,
        type=payload.type,
        text_value=payload.text,
        source_refs=payload.source_refs,
    )
    db.commit()
    db.refresh(doc)
    return MemoryDocumentResponse(
        doc_id=str(doc.doc_id),
        family_id=doc.family_id,
        type=doc.type,
        text=doc.text,
        source_refs=doc.source_refs_jsonb or [],
        created_at=doc.created_at,
    )


@router.post("/search", response_model=MemorySearchResponse)
def search_memory(
    family_id: int,
    payload: MemorySearchRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family(db, family_id)
    if ctx is not None:
        require_family_member(db, family_id, ctx.email)
    hits = semantic_search(db, family_id=family_id, query=payload.query, top_k=payload.top_k)
    return MemorySearchResponse(items=hits)
