from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.documents import Document, IndexJob
from app.services import decision_api, question_api
from app.services.documents import reindex_document


def enqueue_job(
    db: Session,
    *,
    family_id: int,
    job_type: str,
    payload: dict[str, Any],
    actor: str | None = None,
    dedupe_key: str | None = None,
) -> IndexJob:
    existing = None
    if dedupe_key:
        existing = db.execute(
            select(IndexJob).where(
                IndexJob.family_id == family_id,
                IndexJob.job_type == job_type,
                IndexJob.dedupe_key == dedupe_key,
            )
        ).scalar_one_or_none()
    if existing is not None and existing.status in {"pending", "running", "completed"}:
        existing.payload_jsonb = payload
        existing.actor = actor
        existing.updated_at = datetime.now(UTC)
        return existing
    if existing is None:
        existing = IndexJob(
            family_id=family_id,
            job_type=job_type,
            status="pending",
            actor=actor,
            dedupe_key=dedupe_key,
            payload_jsonb=payload,
        )
        db.add(existing)
        db.flush()
        return existing
    existing.status = "pending"
    existing.payload_jsonb = payload
    existing.actor = actor
    existing.attempts = 0
    existing.error_text = None
    existing.result_jsonb = None
    existing.scheduled_for = datetime.now(UTC)
    existing.completed_at = None
    existing.started_at = None
    existing.lease_expires_at = None
    existing.updated_at = datetime.now(UTC)
    return existing


def claim_pending_jobs(db: Session, *, limit: int = 25, lease_seconds: int = 300) -> list[IndexJob]:
    now = datetime.now(UTC)
    query: Select[IndexJob] = (
        select(IndexJob)
        .where(IndexJob.status == "pending", IndexJob.scheduled_for <= now)
        .order_by(IndexJob.scheduled_for.asc(), IndexJob.created_at.asc())
        .limit(limit)
    )
    jobs = list(db.execute(query).scalars().all())
    lease_expires_at = now + timedelta(seconds=max(30, lease_seconds))
    for job in jobs:
        job.status = "running"
        job.started_at = now
        job.lease_expires_at = lease_expires_at
        job.attempts += 1
        job.updated_at = now
    return jobs


def complete_job(db: Session, job: IndexJob, *, result: dict[str, Any] | None = None) -> None:
    job.status = "completed"
    job.completed_at = datetime.now(UTC)
    job.result_jsonb = result or {}
    job.error_text = None
    job.lease_expires_at = None
    job.updated_at = datetime.now(UTC)


def fail_job(db: Session, job: IndexJob, *, error_text: str) -> None:
    job.status = "failed"
    job.completed_at = datetime.now(UTC)
    job.error_text = error_text[:4000]
    job.lease_expires_at = None
    job.updated_at = datetime.now(UTC)


def _process_create_question(job: IndexJob) -> dict[str, Any]:
    payload = dict(job.payload_jsonb or {})
    actor = str(job.actor or payload.get("actor") or "").strip().lower() or None
    return question_api.create_question(
        family_id=job.family_id,
        actor_email=actor,
        payload=payload,
    )


def _process_mirror_memory(job: IndexJob) -> dict[str, Any]:
    payload = dict(job.payload_jsonb or {})
    actor = str(job.actor or payload.get("actor") or "").strip().lower() or None
    decision_api.write_family_memory(
        family_id=job.family_id,
        actor_email=actor,
        internal_admin=False,
        type=str(payload.get("type") or "note"),
        text=str(payload.get("text") or ""),
        owner_person_id=str(payload.get("owner_person_id") or "") or None,
        visibility_scope=str(payload.get("visibility_scope") or "family"),
        source_refs=list(payload.get("source_refs") or []),
    )
    return {"mirrored": True}


def _process_reindex_document(db: Session, job: IndexJob) -> dict[str, Any]:
    payload = dict(job.payload_jsonb or {})
    provider_file_id = str(payload.get("provider_file_id") or "").strip() or None
    path = str(payload.get("path") or "").strip() or None
    document = None
    if provider_file_id:
        document = db.execute(
            select(Document).where(
                Document.family_id == job.family_id,
                Document.provider == "nextcloud",
                Document.provider_file_id == provider_file_id,
            )
        ).scalar_one_or_none()
    if document is None and path:
        document = db.execute(
            select(Document).where(Document.family_id == job.family_id, Document.path == path)
        ).scalar_one_or_none()
    if document is None:
        return {"reindexed": False, "reason": "document_not_found", "path": path, "provider_file_id": provider_file_id}
    result = reindex_document(db, document=document)
    return {"reindexed": True, **result}


def process_pending_jobs(db: Session, *, limit: int = 25) -> dict[str, Any]:
    jobs = claim_pending_jobs(db, limit=limit)
    processed = 0
    failed = 0
    for job in jobs:
        try:
            if job.job_type == "create_question":
                result = _process_create_question(job)
            elif job.job_type == "mirror_memory":
                result = _process_mirror_memory(job)
            elif job.job_type == "reindex_document":
                result = _process_reindex_document(db, job)
            else:
                result = {"skipped": True, "reason": "unsupported_job_type"}
            complete_job(db, job, result=result)
            processed += 1
        except Exception as exc:
            fail_job(db, job, error_text=str(exc))
            failed += 1
    return {"claimed": len(jobs), "processed": processed, "failed": failed}
