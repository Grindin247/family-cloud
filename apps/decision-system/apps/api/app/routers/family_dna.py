from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.schemas.family_dna import DnaCommitResponse, DnaProposeRequest, DnaProposeResponse, DnaSnapshotResponse
from app.services.access import require_family, require_family_editor, require_family_member
from app.services.family_dna import commit_proposal, get_latest_snapshot, propose_patch

router = APIRouter(prefix="/v1/family/{family_id}/dna", tags=["family-dna"])


@router.get("", response_model=DnaSnapshotResponse)
def get_dna_snapshot(
    family_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    require_family(db, family_id)
    if ctx is not None:
        require_family_member(db, family_id, ctx.email)
    snap = get_latest_snapshot(db, family_id)
    db.commit()
    db.refresh(snap)
    return DnaSnapshotResponse(
        family_id=family_id,
        version=snap.version,
        snapshot=snap.snapshot_jsonb or {},
        updated_at=snap.updated_at,
        updated_by=snap.updated_by,
    )


@router.post("/propose", response_model=DnaProposeResponse, status_code=201)
def propose_dna_patch(
    family_id: int,
    payload: DnaProposeRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family(db, family_id)
    actor = (ctx.email if ctx is not None else (x_dev_user or "dev")).strip().lower()
    if ctx is not None:
        require_family_editor(db, family_id, ctx.email)
    proposal = propose_patch(
        db,
        family_id=family_id,
        actor=actor,
        patch_ops=[op.model_dump(by_alias=True) for op in payload.patch],
        rationale=payload.rationale,
        confidence=payload.confidence,
        sources=payload.sources,
    )
    db.commit()
    return DnaProposeResponse(proposal_id=str(proposal.proposal_id), status=proposal.status)


@router.post("/commit/{proposal_id}", response_model=DnaCommitResponse)
def commit_dna_patch(
    family_id: int,
    proposal_id: str,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family(db, family_id)
    actor = (ctx.email if ctx is not None else (x_dev_user or "dev")).strip().lower()
    if ctx is not None:
        require_family_editor(db, family_id, ctx.email)
    version, event_id = commit_proposal(db, family_id=family_id, actor=actor, proposal_id=uuid.UUID(proposal_id))
    db.commit()
    return DnaCommitResponse(family_id=family_id, version=version, event_id=str(event_id))
