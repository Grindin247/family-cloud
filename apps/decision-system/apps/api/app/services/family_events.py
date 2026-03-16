from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.common.family_events import make_privacy, validate_event_envelope
from app.models.entities import AgentPlaybackEvent, AgentUsageEvent
from app.models.family_events import FamilyEventDeadLetter, FamilyEventExportJob, FamilyEventRecord


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _json_loads(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload or {})
    for key in ("body_text", "content", "raw_text", "text", "note_body", "summary_text"):
        sanitized.pop(key, None)
    return sanitized


def make_backend_event_payload(
    *,
    family_id: int,
    domain: str,
    event_type: str,
    actor_id: str,
    actor_type: str,
    subject_id: str,
    subject_type: str,
    payload: dict[str, Any],
    source_agent_id: str,
    source_runtime: str = "backend",
    source_session_id: str | None = None,
    source_request_id: str | None = None,
    tags: list[str] | None = None,
    privacy: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> dict[str, Any]:
    from agents.common.family_events import build_event

    return build_event(
        family_id=family_id,
        domain=domain,
        event_type=event_type,
        actor={"actor_type": actor_type, "actor_id": actor_id},
        subject={"subject_type": subject_type, "subject_id": subject_id},
        payload=payload,
        source={
            "agent_id": source_agent_id,
            "runtime": source_runtime,
            "request_id": source_request_id,
            "session_id": source_session_id,
        },
        privacy=privacy or make_privacy(),
        tags=tags or [],
        correlation_id=correlation_id,
        causation_id=causation_id,
        integrity={"producer": source_agent_id},
    )


def _validate_domain_payload(event: dict[str, Any]) -> None:
    payload = event.get("payload") or {}
    event_type = str(event["event_type"])
    if event_type == "decision.score_calculated" and "score_value" not in payload:
        raise ValueError("decision.score_calculated payload requires score_value")
    if event_type == "task.completed" and "completed_by" not in payload:
        raise ValueError("task.completed payload requires completed_by")
    if event_type in {"note.created", "file.indexed"} and ("path" not in payload and "file_id" not in payload and "note_id" not in payload):
        raise ValueError(f"{event_type} payload requires a stable reference")


def _title_and_summary(event_type: str, payload: dict[str, Any], domain: str) -> tuple[str, str]:
    subject_name = str(payload.get("title") or payload.get("name") or payload.get("path") or payload.get("note_type") or domain).strip()
    mapping = {
        "decision.created": ("Decision created", f"Decision created: {subject_name}"),
        "decision.updated": ("Decision updated", f"Decision updated: {subject_name}"),
        "decision.score_calculated": ("Decision scored", f"Decision scored for {subject_name}"),
        "decision.approved": ("Decision approved", f"Decision approved: {subject_name}"),
        "decision.rejected": ("Decision rejected", f"Decision rejected: {subject_name}"),
        "task.created": ("Task created", f"Task created: {subject_name}"),
        "task.updated": ("Task updated", f"Task updated: {subject_name}"),
        "task.assigned": ("Task assigned", f"Task assigned: {subject_name}"),
        "task.completed": ("Task completed", f"Task completed: {subject_name}"),
        "task.overdue": ("Task overdue", f"Task overdue: {subject_name}"),
        "task.deleted": ("Task deleted", f"Task deleted: {subject_name}"),
        "file.indexed": ("File indexed", f"File indexed: {subject_name}"),
        "file.filed": ("File filed", f"File filed: {subject_name}"),
        "file.tagged": ("File tagged", f"File tagged: {subject_name}"),
        "file.deleted": ("File deleted", f"File deleted: {subject_name}"),
        "note.created": ("Note created", f"Note created: {subject_name}"),
        "note.summarized": ("Note summarized", f"Note summarized: {subject_name}"),
    }
    return mapping.get(event_type, (event_type.replace(".", " ").title(), f"{event_type}"))


def bridge_family_event_to_legacy(db: Session, *, record: FamilyEventRecord) -> tuple[int | None, int | None]:
    payload = _json_loads(record.payload_json, {})
    title, summary = _title_and_summary(record.event_type, payload, record.domain)
    value_number = None
    if record.event_type == "decision.score_calculated":
        try:
            value_number = float(payload.get("score_value"))
        except Exception:
            value_number = None
    usage_event_type = record.event_type.replace(".", "_")
    usage = AgentUsageEvent(
        family_id=record.family_id,
        domain=record.domain,
        source_agent=str((_json_loads(record.source_json, {}) or {}).get("agent_id") or "unknown"),
        actor=record.actor_id or "system",
        event_type=usage_event_type,
        topic=title,
        status=None,
        value_number=value_number,
        payload_json=_json_dumps(record.payload_json),
        created_at=record.occurred_at,
    )
    playback = AgentPlaybackEvent(
        family_id=record.family_id,
        domain=record.domain,
        source_agent=str((_json_loads(record.source_json, {}) or {}).get("agent_id") or "unknown"),
        actor=record.actor_id or "system",
        event_type=usage_event_type,
        summary=summary,
        topic=title,
        payload_json=_json_dumps(record.payload_json),
        created_at=record.occurred_at,
    )
    db.add(usage)
    db.add(playback)
    db.flush()
    record.legacy_usage_event_id = usage.id
    record.legacy_playback_event_id = playback.id
    db.flush()
    return usage.id, playback.id


def ingest_family_event(db: Session, event: dict[str, Any], *, subject: str) -> FamilyEventRecord:
    validate_event_envelope(event)
    _validate_domain_payload(event)
    payload = _sanitize_payload(dict(event.get("payload") or {}))
    existing = db.execute(select(FamilyEventRecord).where(FamilyEventRecord.event_id == str(event["event_id"]))).scalar_one_or_none()
    if existing is not None:
        return existing
    actor = dict(event.get("actor") or {})
    subject_ref = dict(event.get("subject") or {})
    correlation = dict(event.get("correlation") or {})
    privacy = dict(event.get("privacy") or {})
    record = FamilyEventRecord(
        event_id=str(event["event_id"]),
        schema_version=int(event["schema_version"]),
        event_version=int(event["event_version"]),
        occurred_at=datetime.fromisoformat(str(event["occurred_at"]).replace("Z", "+00:00")),
        recorded_at=datetime.fromisoformat(str(event["recorded_at"]).replace("Z", "+00:00")),
        family_id=int(event["family_id"]),
        domain=str(event["domain"]),
        event_type=str(event["event_type"]),
        actor_type=str(actor.get("actor_type") or "system"),
        actor_id=str(actor.get("actor_id")) if actor.get("actor_id") is not None else None,
        subject_type=str(subject_ref.get("subject_type") or "item"),
        subject_id=str(subject_ref.get("subject_id") or "unknown"),
        correlation_id=str(correlation.get("correlation_id")) if correlation.get("correlation_id") is not None else None,
        causation_id=str(correlation.get("causation_id")) if correlation.get("causation_id") is not None else None,
        parent_event_id=str(correlation.get("parent_event_id")) if correlation.get("parent_event_id") is not None else None,
        privacy_classification=str(privacy.get("classification") or "family"),
        export_policy=str(privacy.get("export_policy") or "restricted"),
        tags_json=event.get("tags") or [],
        payload_json=payload,
        actor_json=actor,
        subject_json=subject_ref,
        source_json=event.get("source") or {},
        privacy_json=privacy,
        integrity_json=event.get("integrity"),
        raw_event_json={**event, "payload": payload, "_subject": subject},
    )
    db.add(record)
    db.flush()
    bridge_family_event_to_legacy(db, record=record)
    db.flush()
    return record


def ingest_or_dead_letter_family_event(
    db: Session,
    *,
    raw_event: dict[str, Any] | str,
    subject: str,
) -> tuple[FamilyEventRecord | None, FamilyEventDeadLetter | None]:
    try:
        event = raw_event if isinstance(raw_event, dict) else json.loads(raw_event)
        if not isinstance(event, dict):
            raise ValueError("canonical family event payload must decode to an object")
        record = ingest_family_event(db, event, subject=subject)
        db.commit()
        return record, None
    except Exception as exc:
        db.rollback()
        dead_letter = dead_letter_family_event(db, subject=subject, raw_event=raw_event, error=exc)
        db.commit()
        return None, dead_letter


def dead_letter_family_event(db: Session, *, subject: str, raw_event: dict[str, Any] | str, error: Exception | str) -> FamilyEventDeadLetter:
    event_id = None
    if isinstance(raw_event, dict):
        event_id = raw_event.get("event_id")
        raw_payload = raw_event
    else:
        raw_payload = {"raw": raw_event}
    row = FamilyEventDeadLetter(
        event_id=str(event_id) if event_id is not None else None,
        subject=subject,
        raw_event_json=raw_payload,
        error_json={"error": str(error)},
    )
    db.add(row)
    db.flush()
    return row


def list_family_events(
    db: Session,
    *,
    family_id: int,
    domain: str | None = None,
    event_type: str | None = None,
    subject_id: str | None = None,
    actor_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = select(FamilyEventRecord).where(FamilyEventRecord.family_id == family_id)
    if domain:
        query = query.where(FamilyEventRecord.domain == domain)
    if event_type:
        query = query.where(FamilyEventRecord.event_type == event_type)
    if subject_id:
        query = query.where(FamilyEventRecord.subject_id == subject_id)
    if actor_id:
        query = query.where(FamilyEventRecord.actor_id == actor_id)
    if start:
        query = query.where(FamilyEventRecord.occurred_at >= start)
    if end:
        query = query.where(FamilyEventRecord.occurred_at <= end)
    rows = db.execute(query.order_by(FamilyEventRecord.occurred_at.desc()).offset(offset).limit(limit)).scalars().all()
    return [
        {
            "event_id": row.event_id,
            "family_id": row.family_id,
            "domain": row.domain,
            "event_type": row.event_type,
            "event_version": row.event_version,
            "occurred_at": row.occurred_at,
            "recorded_at": row.recorded_at,
            "actor_id": row.actor_id,
            "actor_type": row.actor_type,
            "subject_id": row.subject_id,
            "subject_type": row.subject_type,
            "correlation_id": row.correlation_id,
            "causation_id": row.causation_id,
            "privacy_classification": row.privacy_classification,
            "export_policy": row.export_policy,
            "tags": _json_loads(row.tags_json, []),
            "payload": _json_loads(row.payload_json, {}),
            "source": _json_loads(row.source_json, {}),
        }
        for row in rows
    ]


def build_timeline(
    db: Session,
    *,
    family_id: int,
    domain: str | None = None,
    domains: list[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    query = select(FamilyEventRecord).where(FamilyEventRecord.family_id == family_id)
    if domain:
        query = query.where(FamilyEventRecord.domain == domain)
    if domains:
        query = query.where(FamilyEventRecord.domain.in_(domains))
    if start:
        query = query.where(FamilyEventRecord.occurred_at >= start)
    if end:
        query = query.where(FamilyEventRecord.occurred_at <= end)
    rows = db.execute(query.order_by(FamilyEventRecord.occurred_at.desc()).limit(limit)).scalars().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        payload = _json_loads(row.payload_json, {})
        title, summary = _title_and_summary(row.event_type, payload, row.domain)
        items.append(
            {
                "occurred_at": row.occurred_at,
                "domain": row.domain,
                "event_type": row.event_type,
                "title": title,
                "summary": summary,
                "subject_id": row.subject_id,
                "tags": _json_loads(row.tags_json, []),
            }
        )
    return items


def query_counts(
    db: Session,
    *,
    family_id: int,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    rows = list_family_events(db, family_id=family_id, start=start, end=end, limit=5000, offset=0)
    metrics = {
        "notes.created.count": 0.0,
        "tasks.completed.count": 0.0,
        "decisions.created.count": 0.0,
        "decision.goal_alignment.avg": 0.0,
        "church.notes.count": 0.0,
    }
    score_values: list[float] = []
    for row in rows:
        payload = row["payload"]
        if row["event_type"] == "note.created":
            metrics["notes.created.count"] += 1.0
            if payload.get("note_type") == "church" or "church" in row.get("tags", []):
                metrics["church.notes.count"] += 1.0
        elif row["event_type"] == "task.completed":
            metrics["tasks.completed.count"] += 1.0
        elif row["event_type"] == "decision.created":
            metrics["decisions.created.count"] += 1.0
        elif row["event_type"] == "decision.score_calculated" and payload.get("score_type", "goal_alignment") == "goal_alignment":
            try:
                score_values.append(float(payload["score_value"]))
            except Exception:
                pass
    if score_values:
        metrics["decision.goal_alignment.avg"] = sum(score_values) / len(score_values)
    return [{"metric": key, "value": value} for key, value in metrics.items()]


def query_time_series(
    db: Session,
    *,
    family_id: int,
    metric: str,
    bucket: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    if bucket not in {"day", "week", "month"}:
        raise ValueError("bucket must be day, week, or month")
    rows = list_family_events(db, family_id=family_id, start=start, end=end, limit=5000, offset=0)
    bucketed: dict[str, float] = {}
    bucket_counts: dict[str, int] = {}
    for row in rows:
        occurred_at: datetime = row["occurred_at"]
        if bucket == "day":
            bucket_key = occurred_at.strftime("%Y-%m-%dT00:00:00+00:00")
        elif bucket == "week":
            monday = occurred_at.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=occurred_at.weekday())
            bucket_key = monday.isoformat()
        else:
            bucket_key = occurred_at.strftime("%Y-%m-01T00:00:00+00:00")
        payload = row["payload"]
        increment = 0.0
        if metric == "notes.created.count" and row["event_type"] == "note.created":
            increment = 1.0
        elif metric == "tasks.completed.count" and row["event_type"] == "task.completed":
            increment = 1.0
        elif metric == "decisions.created.count" and row["event_type"] == "decision.created":
            increment = 1.0
        elif metric == "church.notes.count" and row["event_type"] == "note.created" and (payload.get("note_type") == "church" or "church" in row.get("tags", [])):
            increment = 1.0
        elif metric == "decision.goal_alignment.avg" and row["event_type"] == "decision.score_calculated":
            try:
                increment = float(payload["score_value"])
            except Exception:
                increment = 0.0
        else:
            continue
        bucketed[bucket_key] = bucketed.get(bucket_key, 0.0) + increment
        bucket_counts[bucket_key] = bucket_counts.get(bucket_key, 0) + 1
    points: list[dict[str, Any]] = []
    for key, value in sorted(bucketed.items()):
        final_value = value
        if metric == "decision.goal_alignment.avg" and bucket_counts.get(key):
            final_value = value / float(bucket_counts[key])
        points.append({"bucket_start": datetime.fromisoformat(key), "value": final_value})
    return points


def export_family_events_jsonl(
    db: Session,
    *,
    family_id: int,
    actor: str,
    output_path: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> FamilyEventExportJob:
    rows = list_family_events(db, family_id=family_id, start=start, end=end, limit=10000, offset=0)
    job = FamilyEventExportJob(
        family_id=family_id,
        status="running",
        export_format="jsonl",
        options_json={"start": start.isoformat() if start else None, "end": end.isoformat() if end else None},
        output_path=output_path,
        created_by=actor,
    )
    db.add(job)
    db.flush()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for idx, row in enumerate(rows, start=1):
            payload = row["payload"]
            pseudo = hashlib.sha256(f"{family_id}:{row['actor_id'] or 'system'}".encode("utf-8")).hexdigest()[:12]
            exported = {
                "family_pseudo_id": f"fam_{family_id}",
                "actor_pseudo_id": f"act_{pseudo}",
                "domain": row["domain"],
                "event_type": row["event_type"],
                "time_bucket": row["occurred_at"].strftime("%Y-%m"),
                "payload": payload,
                "sequence_index": idx,
            }
            handle.write(_json_dumps(exported) + "\n")
    job.status = "completed"
    job.completed_at = _utcnow()
    db.flush()
    return job
