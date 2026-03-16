from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import jsonpatch
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.common.events.subjects import Subjects
from agents.common.models.family_dna import FamilyDnaSnapshot as FamilyDnaSnapshotModel
from app.models.family_dna import FamilyDnaEvent, FamilyDnaPatchProposal, FamilyDnaSnapshot
from app.services.event_bus import publish_event
from app.services.memory import create_document_with_embeddings
from app.services.secrets import scan_no_secrets


def get_latest_snapshot(db: Session, family_id: int) -> FamilyDnaSnapshot:
    snap = db.get(FamilyDnaSnapshot, family_id)
    if snap is None:
        snap = FamilyDnaSnapshot(family_id=family_id, version=0, snapshot_jsonb={}, updated_by="system")
        db.add(snap)
        db.flush()
    return snap


def propose_patch(
    db: Session,
    *,
    family_id: int,
    actor: str,
    patch_ops: list[dict[str, Any]],
    rationale: str,
    confidence: float | None,
    sources: list[dict[str, Any]] | None,
) -> FamilyDnaPatchProposal:
    findings = scan_no_secrets({"patch": patch_ops, "rationale": rationale, "sources": sources or []})
    if findings:
        raise HTTPException(status_code=400, detail={"error": "patch contains potential secrets", "findings": findings})

    proposal = FamilyDnaPatchProposal(
        family_id=family_id,
        actor=actor,
        patch_jsonb=patch_ops,
        status="proposed",
        rationale=rationale or "",
        confidence=confidence,
        sources_jsonb=sources or [],
    )
    db.add(proposal)
    db.flush()
    return proposal


def commit_proposal(
    db: Session,
    *,
    family_id: int,
    actor: str,
    proposal_id: uuid.UUID,
) -> tuple[int, uuid.UUID]:
    proposal = db.get(FamilyDnaPatchProposal, proposal_id)
    if proposal is None or proposal.family_id != family_id:
        raise HTTPException(status_code=404, detail="proposal not found")
    if proposal.status != "proposed":
        raise HTTPException(status_code=400, detail=f"proposal status is {proposal.status}")

    snap = get_latest_snapshot(db, family_id)
    current = snap.snapshot_jsonb or {}
    try:
        patched = jsonpatch.apply_patch(current, proposal.patch_jsonb, in_place=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid patch: {exc}") from exc

    findings = scan_no_secrets(patched)
    if findings:
        raise HTTPException(status_code=400, detail={"error": "snapshot contains potential secrets", "findings": findings})

    # Schema validation (strict structure).
    try:
        validated = FamilyDnaSnapshotModel.model_validate(patched).model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"schema validation failed: {exc}") from exc

    next_version = int(snap.version) + 1
    snap.version = next_version
    snap.snapshot_jsonb = validated
    snap.updated_at = datetime.now(timezone.utc)
    snap.updated_by = actor

    event_id = uuid.uuid4()
    db.add(
        FamilyDnaEvent(
            event_id=event_id,
            family_id=family_id,
            actor=actor,
            type="family.dna.updated",
            patch_jsonb=proposal.patch_jsonb,
            rationale=proposal.rationale or "",
            confidence=proposal.confidence,
            sources_jsonb=proposal.sources_jsonb,
            result_version=next_version,
        )
    )
    proposal.status = "committed"

    # Semantic memory: store a compact rationale + patch summary.
    try:
        create_document_with_embeddings(
            db,
            family_id=family_id,
            type="dna",
            text_value=f"Family DNA updated to version {next_version}. Rationale: {proposal.rationale or ''}. Patch: {proposal.patch_jsonb}",
            source_refs=[],
        )
    except Exception:
        pass

    try:
        publish_event(
            Subjects.FAMILY_DNA_UPDATED,
            {"version": next_version, "proposal_id": str(proposal_id)},
            actor=actor,
            family_id=family_id,
            source="decision-api.family_dna",
        )
    except Exception:
        pass

    return next_version, event_id
