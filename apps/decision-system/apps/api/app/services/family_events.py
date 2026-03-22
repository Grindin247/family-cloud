from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
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


KNOWN_DOMAINS = ("decision", "task", "file", "note", "education", "profile", "planning")
METADATA_TOPIC_KEYS = ("note_type", "category", "project", "bucket", "status", "score_type", "area", "goal")


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload or {})
    for key in ("body_text", "content", "raw_text", "text", "note_body", "summary_text"):
        sanitized.pop(key, None)
    return sanitized


def _normalize_string_list(values: Iterable[str] | None) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        item = str(value).strip()
        if item:
            normalized.append(item)
    return normalized


def _record_to_event_dict(row: FamilyEventRecord) -> dict[str, Any]:
    return {
        "event_id": row.event_id,
        "family_id": row.family_id,
        "domain": row.domain,
        "event_type": row.event_type,
        "event_version": row.event_version,
        "occurred_at": row.occurred_at,
        "recorded_at": row.recorded_at,
        "actor_id": row.actor_id,
        "actor_person_id": row.actor_person_id,
        "actor_type": row.actor_type,
        "subject_id": row.subject_id,
        "subject_type": row.subject_type,
        "subject_person_id": row.subject_person_id,
        "correlation_id": row.correlation_id,
        "causation_id": row.causation_id,
        "privacy_classification": row.privacy_classification,
        "export_policy": row.export_policy,
        "tags": _json_loads(row.tags_json, []),
        "payload": _json_loads(row.payload_json, {}),
        "source": _json_loads(row.source_json, {}),
        "integrity": _json_loads(row.integrity_json, {}),
    }


def _query_family_event_rows(
    db: Session,
    *,
    family_id: int,
    domain: str | None = None,
    domains: list[str] | None = None,
    event_type: str | None = None,
    tag: str | None = None,
    subject_id: str | None = None,
    actor_id: str | None = None,
    actor_person_id: str | None = None,
    subject_person_id: str | None = None,
    scope_type: str | None = None,
    target_person_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[FamilyEventRecord]:
    query = select(FamilyEventRecord).where(FamilyEventRecord.family_id == family_id)
    domain_list = _normalize_string_list(domains)
    if domain:
        query = query.where(FamilyEventRecord.domain == domain)
    if domain_list:
        query = query.where(FamilyEventRecord.domain.in_(domain_list))
    if event_type:
        query = query.where(FamilyEventRecord.event_type == event_type)
    if subject_id:
        query = query.where(FamilyEventRecord.subject_id == subject_id)
    if actor_id:
        query = query.where(FamilyEventRecord.actor_id == actor_id)
    if actor_person_id:
        query = query.where(FamilyEventRecord.actor_person_id == actor_person_id)
    if subject_person_id:
        query = query.where(FamilyEventRecord.subject_person_id == subject_person_id)
    if start:
        query = query.where(FamilyEventRecord.occurred_at >= start)
    if end:
        query = query.where(FamilyEventRecord.occurred_at <= end)
    rows = db.execute(query.order_by(FamilyEventRecord.occurred_at.desc())).scalars().all()
    filtered = rows
    if tag:
        needle = tag.strip().lower()
        filtered = [row for row in filtered if needle in {str(item).strip().lower() for item in _json_loads(row.tags_json, [])}]
    if scope_type:
        filtered = [row for row in filtered if str((_json_loads(row.payload_json, {}) or {}).get("scope_type") or "").strip().lower() == scope_type.strip().lower()]
    if target_person_id:
        filtered = [row for row in filtered if str((_json_loads(row.payload_json, {}) or {}).get("target_person_id") or "").strip() == target_person_id.strip()]
    return filtered


def _filter_event_dicts(
    events: list[dict[str, Any]],
    *,
    metric: str | None = None,
) -> list[dict[str, Any]]:
    if not metric or metric == "events.count":
        return events
    filtered: list[dict[str, Any]] = []
    for row in events:
        payload = row["payload"]
        event_type = row["event_type"]
        if metric == "notes.created.count" and event_type == "note.created":
            filtered.append(row)
        elif metric == "tasks.created.count" and event_type == "task.created":
            filtered.append(row)
        elif metric == "tasks.completed.count" and event_type == "task.completed":
            filtered.append(row)
        elif metric == "tasks.overdue.count" and event_type == "task.overdue":
            filtered.append(row)
        elif metric == "decisions.created.count" and event_type == "decision.created":
            filtered.append(row)
        elif metric == "decisions.completed.count" and event_type == "decision.completed":
            filtered.append(row)
        elif metric == "decisions.below_threshold.count" and event_type == "decision.score_below_threshold":
            filtered.append(row)
        elif metric == "goals.updated.count" and event_type in {"goal.created", "goal.updated", "goal.deleted"}:
            filtered.append(row)
        elif metric == "church.notes.count" and event_type == "note.created" and (payload.get("note_type") == "church" or "church" in row.get("tags", [])):
            filtered.append(row)
        elif metric == "decision.goal_alignment.avg" and event_type == "decision.score_calculated" and payload.get("score_type", "goal_alignment") == "goal_alignment":
            filtered.append(row)
    return filtered


def _metric_value(events: list[dict[str, Any]], metric: str) -> float:
    if metric == "decision.goal_alignment.avg":
        values: list[float] = []
        for row in _filter_event_dicts(events, metric=metric):
            try:
                values.append(float(row["payload"]["score_value"]))
            except Exception:
                continue
        return sum(values) / len(values) if values else 0.0
    return float(len(_filter_event_dicts(events, metric=metric)))


def _timeline_item_from_event(row: dict[str, Any]) -> dict[str, Any]:
    title, summary = _title_and_summary(row["event_type"], row["payload"], row["domain"])
    return {
        "occurred_at": row["occurred_at"],
        "domain": row["domain"],
        "event_type": row["event_type"],
        "title": title,
        "summary": summary,
        "subject_id": row["subject_id"],
        "tags": row.get("tags", []),
    }


def make_backend_event_payload(
    *,
    family_id: int,
    domain: str,
    event_type: str,
    actor_id: str,
    actor_type: str,
    actor_person_id: str | None = None,
    subject_id: str,
    subject_type: str,
    subject_person_id: str | None = None,
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
        actor={"actor_type": actor_type, "actor_id": actor_id, "person_id": actor_person_id},
        subject={"subject_type": subject_type, "subject_id": subject_id, "person_id": subject_person_id},
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
        "goal.created": ("Goal created", f"Goal created: {subject_name}"),
        "goal.updated": ("Goal updated", f"Goal updated: {subject_name}"),
        "goal.deleted": ("Goal deleted", f"Goal deleted: {subject_name}"),
        "decision.created": ("Decision created", f"Decision created: {subject_name}"),
        "decision.updated": ("Decision updated", f"Decision updated: {subject_name}"),
        "decision.score_calculated": ("Decision scored", f"Decision scored for {subject_name}"),
        "decision.score_above_threshold": ("Decision above threshold", f"Decision cleared threshold: {subject_name}"),
        "decision.score_below_threshold": ("Decision below threshold", f"Decision fell below threshold: {subject_name}"),
        "decision.approved": ("Decision approved", f"Decision approved: {subject_name}"),
        "decision.rejected": ("Decision rejected", f"Decision rejected: {subject_name}"),
        "decision.deleted": ("Decision deleted", f"Decision deleted: {subject_name}"),
        "decision.completed": ("Decision completed", f"Decision completed: {subject_name}"),
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
        "education.learner.created": ("Learner created", f"Learner created: {subject_name}"),
        "education.learner.updated": ("Learner updated", f"Learner updated: {subject_name}"),
        "education.goal.created": ("Education goal created", f"Education goal created: {subject_name}"),
        "education.goal.updated": ("Education goal updated", f"Education goal updated: {subject_name}"),
        "education.activity.recorded": ("Learning activity recorded", f"Learning activity recorded: {subject_name}"),
        "education.activity.updated": ("Learning activity updated", f"Learning activity updated: {subject_name}"),
        "education.assignment.created": ("Assignment created", f"Assignment created: {subject_name}"),
        "education.assignment.updated": ("Assignment updated", f"Assignment updated: {subject_name}"),
        "education.assessment.recorded": ("Assessment recorded", f"Assessment recorded: {subject_name}"),
        "education.assessment.updated": ("Assessment updated", f"Assessment updated: {subject_name}"),
        "education.practice_repetition.recorded": ("Practice repetition recorded", f"Practice repetition recorded: {subject_name}"),
        "education.practice_repetition.updated": ("Practice repetition updated", f"Practice repetition updated: {subject_name}"),
        "education.journal.recorded": ("Journal recorded", f"Journal recorded: {subject_name}"),
        "education.journal.updated": ("Journal updated", f"Journal updated: {subject_name}"),
        "education.quiz.created": ("Quiz created", f"Quiz created: {subject_name}"),
        "education.quiz.response_recorded": ("Quiz response recorded", f"Quiz response recorded: {subject_name}"),
        "education.attachment.linked": ("Attachment linked", f"Attachment linked: {subject_name}"),
        "profile.person.updated": ("Profile updated", f"Profile updated: {subject_name}"),
        "profile.relationship.created": ("Relationship created", f"Relationship created: {subject_name}"),
        "profile.relationship.updated": ("Relationship updated", f"Relationship updated: {subject_name}"),
        "profile.relationship.deleted": ("Relationship removed", f"Relationship removed: {subject_name}"),
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
        actor_person_id=str(actor.get("person_id")) if actor.get("person_id") is not None else None,
        subject_type=str(subject_ref.get("subject_type") or "item"),
        subject_id=str(subject_ref.get("subject_id") or "unknown"),
        subject_person_id=str(subject_ref.get("person_id")) if subject_ref.get("person_id") is not None else None,
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
    domains: list[str] | None = None,
    event_type: str | None = None,
    tag: str | None = None,
    subject_id: str | None = None,
    actor_id: str | None = None,
    actor_person_id: str | None = None,
    subject_person_id: str | None = None,
    scope_type: str | None = None,
    target_person_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    rows = _query_family_event_rows(
        db,
        family_id=family_id,
        domain=domain,
        domains=domains,
        event_type=event_type,
        tag=tag,
        subject_id=subject_id,
        actor_id=actor_id,
        actor_person_id=actor_person_id,
        subject_person_id=subject_person_id,
        scope_type=scope_type,
        target_person_id=target_person_id,
        start=start,
        end=end,
    )
    return [_record_to_event_dict(row) for row in rows[offset : offset + limit]]


def build_timeline(
    db: Session,
    *,
    family_id: int,
    domain: str | None = None,
    domains: list[str] | None = None,
    event_type: str | None = None,
    tag: str | None = None,
    actor_person_id: str | None = None,
    subject_person_id: str | None = None,
    scope_type: str | None = None,
    target_person_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = list_family_events(
        db,
        family_id=family_id,
        domain=domain,
        domains=domains,
        event_type=event_type,
        tag=tag,
        actor_person_id=actor_person_id,
        subject_person_id=subject_person_id,
        scope_type=scope_type,
        target_person_id=target_person_id,
        start=start,
        end=end,
        limit=limit,
        offset=0,
    )
    return [_timeline_item_from_event(row) for row in rows]


def query_counts(
    db: Session,
    *,
    family_id: int,
    domain: str | None = None,
    domains: list[str] | None = None,
    event_type: str | None = None,
    tag: str | None = None,
    actor_person_id: str | None = None,
    subject_person_id: str | None = None,
    scope_type: str | None = None,
    target_person_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    rows = list_family_events(
        db,
        family_id=family_id,
        domain=domain,
        domains=domains,
        event_type=event_type,
        tag=tag,
        actor_person_id=actor_person_id,
        subject_person_id=subject_person_id,
        scope_type=scope_type,
        target_person_id=target_person_id,
        start=start,
        end=end,
        limit=5000,
        offset=0,
    )
    metrics = {
        "events.count": 0.0,
        "notes.created.count": 0.0,
        "tasks.created.count": 0.0,
        "tasks.completed.count": 0.0,
        "tasks.overdue.count": 0.0,
        "decisions.created.count": 0.0,
        "decisions.completed.count": 0.0,
        "decisions.below_threshold.count": 0.0,
        "goals.updated.count": 0.0,
        "decision.goal_alignment.avg": 0.0,
        "church.notes.count": 0.0,
    }
    score_values: list[float] = []
    for row in rows:
        payload = row["payload"]
        metrics["events.count"] += 1.0
        if row["event_type"] == "note.created":
            metrics["notes.created.count"] += 1.0
            if payload.get("note_type") == "church" or "church" in row.get("tags", []):
                metrics["church.notes.count"] += 1.0
        elif row["event_type"] == "task.created":
            metrics["tasks.created.count"] += 1.0
        elif row["event_type"] == "task.completed":
            metrics["tasks.completed.count"] += 1.0
        elif row["event_type"] == "task.overdue":
            metrics["tasks.overdue.count"] += 1.0
        elif row["event_type"] == "decision.created":
            metrics["decisions.created.count"] += 1.0
        elif row["event_type"] == "decision.completed":
            metrics["decisions.completed.count"] += 1.0
        elif row["event_type"] == "decision.score_below_threshold":
            metrics["decisions.below_threshold.count"] += 1.0
        elif row["event_type"] in {"goal.created", "goal.updated", "goal.deleted"}:
            metrics["goals.updated.count"] += 1.0
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
    domain: str | None = None,
    domains: list[str] | None = None,
    event_type: str | None = None,
    tag: str | None = None,
    actor_person_id: str | None = None,
    subject_person_id: str | None = None,
    scope_type: str | None = None,
    target_person_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    if bucket not in {"day", "week", "month"}:
        raise ValueError("bucket must be day, week, or month")
    rows = list_family_events(
        db,
        family_id=family_id,
        domain=domain,
        domains=domains,
        event_type=event_type,
        tag=tag,
        actor_person_id=actor_person_id,
        subject_person_id=subject_person_id,
        scope_type=scope_type,
        target_person_id=target_person_id,
        start=start,
        end=end,
        limit=5000,
        offset=0,
    )
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
        if metric == "events.count":
            increment = 1.0
        elif metric == "notes.created.count" and row["event_type"] == "note.created":
            increment = 1.0
        elif metric == "tasks.created.count" and row["event_type"] == "task.created":
            increment = 1.0
        elif metric == "tasks.completed.count" and row["event_type"] == "task.completed":
            increment = 1.0
        elif metric == "tasks.overdue.count" and row["event_type"] == "task.overdue":
            increment = 1.0
        elif metric == "decisions.created.count" and row["event_type"] == "decision.created":
            increment = 1.0
        elif metric == "decisions.completed.count" and row["event_type"] == "decision.completed":
            increment = 1.0
        elif metric == "decisions.below_threshold.count" and row["event_type"] == "decision.score_below_threshold":
            increment = 1.0
        elif metric == "goals.updated.count" and row["event_type"] in {"goal.created", "goal.updated", "goal.deleted"}:
            increment = 1.0
        elif metric == "church.notes.count" and row["event_type"] == "note.created" and (payload.get("note_type") == "church" or "church" in row.get("tags", [])):
            increment = 1.0
        elif metric == "decision.goal_alignment.avg" and row["event_type"] == "decision.score_calculated" and payload.get("score_type", "goal_alignment") == "goal_alignment":
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


def get_domain_activity_summary(
    db: Session,
    *,
    family_id: int,
    domain: str | None = None,
    domains: list[str] | None = None,
    event_type: str | None = None,
    tag: str | None = None,
    actor_person_id: str | None = None,
    subject_person_id: str | None = None,
    scope_type: str | None = None,
    target_person_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    rows = list_family_events(
        db,
        family_id=family_id,
        domain=domain,
        domains=domains,
        event_type=event_type,
        tag=tag,
        actor_person_id=actor_person_id,
        subject_person_id=subject_person_id,
        scope_type=scope_type,
        target_person_id=target_person_id,
        start=start,
        end=end,
        limit=10000,
        offset=0,
    )
    grouped: dict[str, dict[str, Any]] = {}
    for domain in KNOWN_DOMAINS:
        grouped[domain] = {
            "domain": domain,
            "total_events": 0,
            "unique_subjects": set(),
            "unique_actors": set(),
            "event_types": Counter(),
            "tags": Counter(),
        }
    for row in rows:
        summary = grouped.setdefault(
            row["domain"],
            {"domain": row["domain"], "total_events": 0, "unique_subjects": set(), "unique_actors": set(), "event_types": Counter(), "tags": Counter()},
        )
        summary["total_events"] += 1
        summary["unique_subjects"].add(row["subject_id"])
        if row["actor_id"]:
            summary["unique_actors"].add(row["actor_id"])
        summary["event_types"][row["event_type"]] += 1
        for tag in row.get("tags", []):
            summary["tags"][tag] += 1
    items: list[dict[str, Any]] = []
    for summary in grouped.values():
        items.append(
            {
                "domain": summary["domain"],
                "total_events": summary["total_events"],
                "unique_subjects": len(summary["unique_subjects"]),
                "unique_actors": len(summary["unique_actors"]),
                "event_types": dict(summary["event_types"].most_common(5)),
                "tags": dict(summary["tags"].most_common(5)),
            }
        )
    return sorted(items, key=lambda item: (-item["total_events"], item["domain"]))


def compare_periods(
    db: Session,
    *,
    family_id: int,
    metric: str,
    current_start: datetime,
    current_end: datetime,
    baseline_start: datetime,
    baseline_end: datetime,
    domain: str | None = None,
    domains: list[str] | None = None,
    event_type: str | None = None,
    tag: str | None = None,
    actor_person_id: str | None = None,
    subject_person_id: str | None = None,
    scope_type: str | None = None,
    target_person_id: str | None = None,
) -> dict[str, Any]:
    current_events = list_family_events(
        db,
        family_id=family_id,
        domain=domain,
        domains=domains,
        event_type=event_type,
        tag=tag,
        actor_person_id=actor_person_id,
        subject_person_id=subject_person_id,
        scope_type=scope_type,
        target_person_id=target_person_id,
        start=current_start,
        end=current_end,
        limit=10000,
        offset=0,
    )
    baseline_events = list_family_events(
        db,
        family_id=family_id,
        domain=domain,
        domains=domains,
        event_type=event_type,
        tag=tag,
        actor_person_id=actor_person_id,
        subject_person_id=subject_person_id,
        scope_type=scope_type,
        target_person_id=target_person_id,
        start=baseline_start,
        end=baseline_end,
        limit=10000,
        offset=0,
    )
    current_value = _metric_value(current_events, metric)
    baseline_value = _metric_value(baseline_events, metric)
    delta = current_value - baseline_value
    delta_pct = None if math.isclose(baseline_value, 0.0) else (delta / baseline_value) * 100.0
    return {
        "metric": metric,
        "baseline": {"start": baseline_start, "end": baseline_end},
        "current": {"start": current_start, "end": current_end},
        "baseline_value": baseline_value,
        "current_value": current_value,
        "delta": delta,
        "delta_pct": delta_pct,
    }


def get_event_sequences(
    db: Session,
    *,
    family_id: int,
    anchor_event_id: str | None = None,
    anchor_occurred_at: datetime | None = None,
    domain: str | None = None,
    domains: list[str] | None = None,
    before_limit: int = 5,
    after_limit: int = 5,
) -> dict[str, Any]:
    if anchor_event_id is None and anchor_occurred_at is None:
        raise ValueError("anchor_event_id or anchor_occurred_at is required")
    rows = list_family_events(
        db,
        family_id=family_id,
        domain=domain,
        domains=domains,
        limit=10000,
        offset=0,
    )
    rows_sorted = sorted(rows, key=lambda item: item["occurred_at"])
    anchor_index = -1
    if anchor_event_id is not None:
        for idx, row in enumerate(rows_sorted):
            if row["event_id"] == anchor_event_id:
                anchor_index = idx
                break
    else:
        for idx, row in enumerate(rows_sorted):
            if row["occurred_at"] >= anchor_occurred_at:
                anchor_index = idx
                break
    if anchor_index == -1:
        return {"anchor": None, "before": [], "after": []}
    anchor_row = rows_sorted[anchor_index]
    before_rows = rows_sorted[max(0, anchor_index - before_limit) : anchor_index]
    after_rows = rows_sorted[anchor_index + 1 : anchor_index + 1 + after_limit]
    return {
        "anchor": _timeline_item_from_event(anchor_row),
        "before": [_timeline_item_from_event(row) for row in reversed(before_rows)],
        "after": [_timeline_item_from_event(row) for row in after_rows],
    }


def get_top_tags_or_topics(
    db: Session,
    *,
    family_id: int,
    domain: str | None = None,
    domains: list[str] | None = None,
    event_type: str | None = None,
    tag: str | None = None,
    actor_person_id: str | None = None,
    subject_person_id: str | None = None,
    scope_type: str | None = None,
    target_person_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    rows = list_family_events(
        db,
        family_id=family_id,
        domain=domain,
        domains=domains,
        event_type=event_type,
        tag=tag,
        actor_person_id=actor_person_id,
        subject_person_id=subject_person_id,
        scope_type=scope_type,
        target_person_id=target_person_id,
        start=start,
        end=end,
        limit=10000,
        offset=0,
    )
    counter: Counter[tuple[str, str]] = Counter()
    for row in rows:
        for tag in row.get("tags", []):
            counter[("tag", str(tag))] += 1
        payload = row["payload"]
        for key in METADATA_TOPIC_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                counter[(f"payload.{key}", value.strip())] += 1
    return [
        {"source": source, "label": label, "count": count}
        for (source, label), count in counter.most_common(limit)
    ]


def get_data_quality_summary(
    db: Session,
    *,
    family_id: int,
    domain: str | None = None,
    domains: list[str] | None = None,
    event_type: str | None = None,
    tag: str | None = None,
    actor_person_id: str | None = None,
    subject_person_id: str | None = None,
    scope_type: str | None = None,
    target_person_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    rows = list_family_events(
        db,
        family_id=family_id,
        domain=domain,
        domains=domains,
        event_type=event_type,
        tag=tag,
        actor_person_id=actor_person_id,
        subject_person_id=subject_person_id,
        scope_type=scope_type,
        target_person_id=target_person_id,
        start=start,
        end=end,
        limit=10000,
        offset=0,
    )
    domain_counts = Counter(row["domain"] for row in rows)
    sparse_domains = [
        {"domain": domain, "count": count, "sparse": count < 3}
        for domain, count in sorted(domain_counts.items())
        if count < 3
    ]
    duplicate_idempotency_keys = 0
    correlation_counter: Counter[str] = Counter()
    idempotency_counter: Counter[str] = Counter()
    max_delay = 0.0
    delayed_recording_events = 0
    for row in rows:
        integrity = row.get("integrity") or {}
        key = integrity.get("idempotency_key")
        if isinstance(key, str) and key.strip():
            idempotency_counter[key.strip()] += 1
        correlation_id = row.get("correlation_id")
        if isinstance(correlation_id, str) and correlation_id.strip():
            correlation_counter[correlation_id.strip()] += 1
        delay_hours = max((row["recorded_at"] - row["occurred_at"]).total_seconds() / 3600.0, 0.0)
        max_delay = max(max_delay, delay_hours)
        if delay_hours >= 24.0:
            delayed_recording_events += 1
    duplicate_idempotency_keys = sum(1 for count in idempotency_counter.values() if count > 1)
    duplicate_correlation_ids = sum(1 for count in correlation_counter.values() if count > 1)
    covered_domains = sorted(domain_counts.keys())
    missing_domains = sorted(domain for domain in KNOWN_DOMAINS if domain not in domain_counts)
    notes: list[str] = []
    if missing_domains:
        notes.append(f"Missing domains in window: {', '.join(missing_domains)}.")
    if delayed_recording_events:
        notes.append(f"{delayed_recording_events} events were recorded at least 24 hours after they occurred.")
    if sparse_domains:
        notes.append("Some domains have sparse coverage in the selected window.")
    return {
        "family_id": family_id,
        "total_events": len(rows),
        "window_start": start,
        "window_end": end,
        "covered_domains": covered_domains,
        "missing_domains": missing_domains,
        "sparse_domains": sparse_domains,
        "duplicate_idempotency_keys": duplicate_idempotency_keys,
        "duplicate_correlation_ids": duplicate_correlation_ids,
        "delayed_recording_events": delayed_recording_events,
        "max_recording_delay_hours": round(max_delay, 2),
        "notes": notes,
    }


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
