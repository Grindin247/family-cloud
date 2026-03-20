from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    AgentPlaybackEvent,
    AgentQuestion,
    AgentQuestionEvent,
    AgentUsageEvent,
    BudgetPolicy,
    Decision,
    DecisionScore,
    Goal,
    RoadmapItem,
)
from app.core.config import settings
from app.services.family_events import make_backend_event_payload
from agents.common.family_events import make_privacy
from app.services.task_ops import latest_task_health_snapshot


ACTIVE_QUESTION_STATUSES = {"pending", "asked", "answered_partial"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _post_canonical_event(event: dict[str, Any]) -> str | None:
    base_url = settings.family_event_api_base_url.rstrip("/")
    if not base_url:
        return None
    headers = {"X-Internal-Admin-Token": settings.family_event_internal_admin_token}
    response = httpx.post(
        f"{base_url}/events",
        json=event,
        headers=headers,
        timeout=20.0,
    )
    response.raise_for_status()
    body = response.json()
    event_body = body.get("event") or {}
    event_id = event_body.get("event_id")
    return str(event_id) if event_id else None


def _question_response(question: AgentQuestion) -> dict[str, Any]:
    return {
        "id": question.id,
        "family_id": question.family_id,
        "domain": question.domain,
        "source_agent": question.source_agent,
        "topic": question.topic,
        "summary": question.summary,
        "prompt": question.prompt,
        "urgency": question.urgency,
        "topic_type": question.topic_type,
        "status": question.status,
        "created_at": question.created_at,
        "updated_at": question.updated_at,
        "expires_at": question.expires_at,
        "due_at": question.due_at,
        "last_asked_at": question.last_asked_at,
        "answer_sufficiency_state": question.answer_sufficiency_state,
        "context": _json_loads(question.context_json, {}),
        "artifact_refs": _json_loads(question.artifact_refs, []),
        "dedupe_key": question.dedupe_key,
    }


def _question_event_response(event: AgentQuestionEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "question_id": event.question_id,
        "family_id": event.family_id,
        "actor": event.actor,
        "event_type": event.event_type,
        "payload": _json_loads(event.payload_json, {}),
        "created_at": event.created_at,
    }


def _playback_event_response(event: AgentPlaybackEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "family_id": event.family_id,
        "domain": event.domain,
        "source_agent": event.source_agent,
        "actor": event.actor,
        "event_type": event.event_type,
        "summary": event.summary,
        "topic": event.topic,
        "payload": _json_loads(event.payload_json, {}),
        "created_at": event.created_at,
    }


def append_question_event(
    db: Session,
    *,
    question_id: str,
    family_id: int,
    actor: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> AgentQuestionEvent:
    event = AgentQuestionEvent(
        question_id=question_id,
        family_id=family_id,
        actor=actor,
        event_type=event_type,
        payload_json=_json_dumps(payload or {}),
    )
    db.add(event)
    db.flush()
    return event


def create_or_update_question(
    db: Session,
    *,
    family_id: int,
    domain: str,
    source_agent: str,
    topic: str,
    summary: str,
    prompt: str,
    urgency: str,
    topic_type: str,
    actor: str,
    dedupe_key: str,
    expires_at: datetime | None = None,
    due_at: datetime | None = None,
    answer_sufficiency_state: str = "unknown",
    context: dict[str, Any] | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = _utcnow()
    question = db.execute(
        select(AgentQuestion).where(
            AgentQuestion.family_id == family_id,
            AgentQuestion.domain == domain,
            AgentQuestion.dedupe_key == dedupe_key,
        )
    ).scalar_one_or_none()
    payload_context = context or {}
    payload_refs = artifact_refs or []

    created = False
    if question is None:
        question = AgentQuestion(
            id=str(uuid.uuid4()),
            family_id=family_id,
            domain=domain,
            source_agent=source_agent,
            topic=topic,
            summary=summary,
            prompt=prompt,
            urgency=urgency,
            topic_type=topic_type,
            status="pending",
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
            due_at=due_at,
            answer_sufficiency_state=answer_sufficiency_state,
            context_json=_json_dumps(payload_context),
            dedupe_key=dedupe_key,
            artifact_refs=_json_dumps(payload_refs),
        )
        db.add(question)
        db.flush()
        created = True
    else:
        current_context = _json_loads(question.context_json, {})
        current_context.update(payload_context)
        question.source_agent = source_agent
        question.topic = topic
        question.summary = summary
        question.prompt = prompt
        question.urgency = urgency
        question.topic_type = topic_type
        question.updated_at = now
        question.expires_at = expires_at
        question.due_at = due_at
        question.answer_sufficiency_state = answer_sufficiency_state
        question.context_json = _json_dumps(current_context)
        question.artifact_refs = _json_dumps(payload_refs)
        if question.status not in ACTIVE_QUESTION_STATUSES:
            question.status = "pending"
        db.flush()

    event = append_question_event(
        db,
        question_id=question.id,
        family_id=family_id,
        actor=actor,
        event_type="created" if created else "updated",
        payload={"topic": topic, "urgency": urgency, "topic_type": topic_type},
    )
    return {"question": _question_response(question), "event": _question_event_response(event)}


def list_questions(
    db: Session,
    *,
    family_id: int,
    domain: str | None = None,
    status: str | None = None,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    query = select(AgentQuestion).where(AgentQuestion.family_id == family_id)
    if domain:
        query = query.where(AgentQuestion.domain == domain)
    if status:
        query = query.where(AgentQuestion.status == status)
    elif not include_inactive:
        query = query.where(AgentQuestion.status.in_(sorted(ACTIVE_QUESTION_STATUSES)))
    items = db.execute(
        query.order_by(AgentQuestion.due_at.is_(None), AgentQuestion.due_at.asc(), AgentQuestion.updated_at.desc())
    ).scalars().all()
    return [_question_response(item) for item in items]


def get_question(db: Session, question_id: str) -> AgentQuestion | None:
    return db.get(AgentQuestion, question_id)


def update_question(
    db: Session,
    *,
    question: AgentQuestion,
    actor: str,
    summary: str | None = None,
    prompt: str | None = None,
    urgency: str | None = None,
    topic_type: str | None = None,
    status: str | None = None,
    expires_at: datetime | None = None,
    due_at: datetime | None = None,
    answer_sufficiency_state: str | None = None,
    context_patch: dict[str, Any] | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if summary is not None:
        question.summary = summary
    if prompt is not None:
        question.prompt = prompt
    if urgency is not None:
        question.urgency = urgency
    if topic_type is not None:
        question.topic_type = topic_type
    if status is not None:
        question.status = status
    if expires_at is not None:
        question.expires_at = expires_at
    if due_at is not None:
        question.due_at = due_at
    if answer_sufficiency_state is not None:
        question.answer_sufficiency_state = answer_sufficiency_state
    if context_patch:
        context = _json_loads(question.context_json, {})
        context.update(context_patch)
        question.context_json = _json_dumps(context)
    if artifact_refs is not None:
        question.artifact_refs = _json_dumps(artifact_refs)
    question.updated_at = _utcnow()
    db.flush()
    event = append_question_event(
        db,
        question_id=question.id,
        family_id=question.family_id,
        actor=actor,
        event_type="updated",
        payload={"status": question.status, "answer_sufficiency_state": question.answer_sufficiency_state},
    )
    return {"question": _question_response(question), "event": _question_event_response(event)}


def mark_question_asked(
    db: Session,
    *,
    question: AgentQuestion,
    actor: str,
    delivery_agent: str,
    delivery_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _utcnow()
    question.status = "asked"
    question.last_asked_at = now
    question.updated_at = now
    db.flush()
    event = append_question_event(
        db,
        question_id=question.id,
        family_id=question.family_id,
        actor=actor,
        event_type="asked",
        payload={"delivery_agent": delivery_agent, "delivery_context": delivery_context or {}},
    )
    return {"question": _question_response(question), "event": _question_event_response(event)}


def resolve_question(
    db: Session,
    *,
    question: AgentQuestion,
    actor: str,
    status: str,
    resolution_note: str | None = None,
    answer_sufficiency_state: str | None = None,
    context_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _utcnow()
    question.status = status
    if answer_sufficiency_state is not None:
        question.answer_sufficiency_state = answer_sufficiency_state
    if context_patch:
        context = _json_loads(question.context_json, {})
        context.update(context_patch)
        question.context_json = _json_dumps(context)
    question.updated_at = now
    db.flush()
    event = append_question_event(
        db,
        question_id=question.id,
        family_id=question.family_id,
        actor=actor,
        event_type=status,
        payload={"resolution_note": resolution_note or "", "answer_sufficiency_state": question.answer_sufficiency_state},
    )
    return {"question": _question_response(question), "event": _question_event_response(event)}


def list_question_history(db: Session, *, family_id: int, question_id: str | None = None) -> list[dict[str, Any]]:
    query = select(AgentQuestionEvent).where(AgentQuestionEvent.family_id == family_id)
    if question_id:
        query = query.where(AgentQuestionEvent.question_id == question_id)
    items = db.execute(query.order_by(AgentQuestionEvent.created_at.desc())).scalars().all()
    return [_question_event_response(item) for item in items]


def expire_questions(db: Session, *, family_id: int | None = None, actor: str = "system") -> int:
    now = _utcnow()
    query = select(AgentQuestion).where(
        AgentQuestion.status.in_(sorted(ACTIVE_QUESTION_STATUSES)),
        AgentQuestion.expires_at.is_not(None),
        AgentQuestion.expires_at < now,
    )
    if family_id is not None:
        query = query.where(AgentQuestion.family_id == family_id)
    items = db.execute(query).scalars().all()
    for item in items:
        item.status = "expired"
        item.updated_at = now
        append_question_event(
            db,
            question_id=item.id,
            family_id=item.family_id,
            actor=actor,
            event_type="expired",
            payload={"expired_at": now.isoformat()},
        )
    db.flush()
    return len(items)


def record_agent_event(
    db: Session,
    *,
    family_id: int,
    domain: str,
    source_agent: str,
    actor: str,
    event_type: str,
    summary: str,
    topic: str | None = None,
    status: str | None = None,
    value_number: float | None = None,
    payload: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    ts = created_at or _utcnow()
    payload_data = payload or {}

    usage = AgentUsageEvent(
        family_id=family_id,
        domain=domain,
        source_agent=source_agent,
        actor=actor,
        event_type=event_type,
        topic=topic,
        status=status,
        value_number=value_number,
        payload_json=_json_dumps(payload_data),
        created_at=ts,
    )
    playback = AgentPlaybackEvent(
        family_id=family_id,
        domain=domain,
        source_agent=source_agent,
        actor=actor,
        event_type=event_type,
        summary=summary,
        topic=topic,
        payload_json=_json_dumps(payload_data),
        created_at=ts,
    )
    db.add(usage)
    db.add(playback)
    db.flush()
    result = {"usage_event_id": usage.id, "playback_event_id": playback.id}

    canonical = _legacy_agent_event_to_canonical(
        family_id=family_id,
        domain=domain,
        source_agent=source_agent,
        actor=actor,
        event_type=event_type,
        topic=topic,
        status=status,
        payload=payload_data,
        created_at=ts,
    )
    if canonical is None:
        return result

    canonical["legacy_usage_event_id"] = usage.id
    canonical["legacy_playback_event_id"] = playback.id
    try:
        result["canonical_event_id"] = _post_canonical_event(canonical)
    except Exception as exc:
        result["canonical_event_id"] = None
        result["canonical_error"] = str(exc)
    return result


def _legacy_agent_event_to_canonical(
    *,
    family_id: int,
    domain: str,
    source_agent: str,
    actor: str,
    event_type: str,
    topic: str | None,
    status: str | None,
    payload: dict[str, Any],
    created_at: datetime,
) -> dict[str, Any] | None:
    normalized_domain = str(domain).strip().lower()
    normalized_type = str(event_type).strip().lower()
    topic_value = (topic or "").strip() or None

    if normalized_domain == "task":
        source_agent_id = "TaskAgent" if source_agent == "TasksAgent" else source_agent
        mapped = {
            "task_created": "task.created",
            "task_updated": "task.updated",
            "task_assigned": "task.assigned",
            "task_completed": "task.completed",
            "task_overdue": "task.overdue",
            "task_deleted": "task.deleted",
        }.get(normalized_type)
        if mapped is None:
            return None
        task_id = payload.get("task_id")
        if task_id is None:
            return None
        canonical_payload = dict(payload)
        canonical_payload.setdefault("task_id", task_id)
        if topic_value and "title" not in canonical_payload:
            canonical_payload["title"] = topic_value
        if status and "status" not in canonical_payload:
            canonical_payload["status"] = status
        if mapped == "task.completed" and "completed_by" not in canonical_payload:
            canonical_payload["completed_by"] = actor
        return make_backend_event_payload(
            family_id=family_id,
            domain="task",
            event_type=mapped,
            actor_id=actor,
            actor_type="user",
            subject_id=str(task_id),
            subject_type="task",
            payload=canonical_payload,
            source_agent_id=source_agent_id,
            source_runtime="backend",
            tags=_string_tags(payload.get("tags")),
            privacy=make_privacy(contains_free_text=False),
        )

    if normalized_domain == "file":
        mapped = {
            "file_indexed": "file.indexed",
            "file_filed": "file.filed",
            "file_tagged": "file.tagged",
            "file_deleted": "file.deleted",
        }.get(normalized_type)
        if mapped is None:
            return None
        subject_id = payload.get("file_id") or payload.get("path")
        if subject_id is None:
            return None
        canonical_payload = dict(payload)
        if topic_value and "title" not in canonical_payload:
            canonical_payload["title"] = topic_value
        if status and "status" not in canonical_payload:
            canonical_payload["status"] = status
        return make_backend_event_payload(
            family_id=family_id,
            domain="file",
            event_type=mapped,
            actor_id=actor,
            actor_type="user",
            subject_id=str(subject_id),
            subject_type="file",
            payload=canonical_payload,
            source_agent_id=source_agent,
            source_runtime="backend",
            tags=_string_tags(payload.get("tags")),
            privacy=make_privacy(contains_free_text=False),
        )

    if normalized_domain == "note":
        mapped = {
            "note_created": "note.created",
            "note_summarized": "note.summarized",
        }.get(normalized_type)
        if mapped is None:
            return None
        subject_id = payload.get("note_id") or payload.get("path")
        if subject_id is None:
            return None
        canonical_payload = dict(payload)
        if topic_value and "title" not in canonical_payload:
            canonical_payload["title"] = topic_value
        if status and "status" not in canonical_payload:
            canonical_payload["status"] = status
        return make_backend_event_payload(
            family_id=family_id,
            domain="note",
            event_type=mapped,
            actor_id=actor,
            actor_type="user",
            subject_id=str(subject_id),
            subject_type="note",
            payload=canonical_payload,
            source_agent_id=source_agent,
            source_runtime="backend",
            tags=_string_tags(payload.get("tags")),
            privacy=make_privacy(contains_free_text=False),
        )

    return None


def _string_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            tags.append(text)
    return tags


def _metric_window_filters(
    query,
    model,
    *,
    family_id: int,
    domain: str | None,
    start_at: datetime | None,
    end_at: datetime | None,
):
    query = query.where(model.family_id == family_id)
    if domain:
        query = query.where(model.domain == domain)
    if start_at:
        query = query.where(model.created_at >= start_at)
    if end_at:
        query = query.where(model.created_at <= end_at)
    return query


def query_metrics(
    db: Session,
    *,
    family_id: int,
    domain: str | None,
    start_at: datetime | None,
    end_at: datetime | None,
    metric_keys: Iterable[str],
) -> list[dict[str, Any]]:
    keys = set(metric_keys or [])
    if not keys:
        keys = {
            "decision_created_count",
            "decision_completion_count",
            "decision_deleted_count",
            "decision_avg_score",
            "decisions_below_threshold_count",
            "goal_updates_count",
            "roadmap_due_soon_backlog_count",
            "question_queue_open_count",
            "question_queue_resolved_count",
            "task_created_count",
            "task_completion_count",
            "task_deleted_count",
            "task_open_count",
            "task_overdue_count",
            "task_load_total",
            "task_load_by_member",
            "task_load_by_project",
            "project_count",
            "stale_task_count",
            "file_indexed_count",
            "file_auto_filed_count",
            "file_review_needed_count",
            "file_delete_requested_count",
            "file_deleted_count",
            "file_inbox_backlog_count",
            "file_unclassified_count",
        }

    window = {"window_start": start_at, "window_end": end_at}
    out: list[dict[str, Any]] = []

    def add(metric_key: str, value: float, *, unit: str = "count", metadata: dict[str, Any] | None = None):
        if metric_key in keys:
            out.append({"metric_key": metric_key, "value": value, "unit": unit, **window, "metadata": metadata or {}})

    usage_base = _metric_window_filters(select(AgentUsageEvent), AgentUsageEvent, family_id=family_id, domain=domain, start_at=start_at, end_at=end_at).subquery()

    created_count = db.execute(select(func.count()).select_from(usage_base).where(usage_base.c.event_type == "decision_created")).scalar_one()
    add("decision_created_count", float(created_count))

    completed_count = db.execute(select(func.count()).select_from(usage_base).where(usage_base.c.event_type == "decision_completed")).scalar_one()
    add("decision_completion_count", float(completed_count))

    deleted_count = db.execute(select(func.count()).select_from(usage_base).where(usage_base.c.event_type == "decision_deleted")).scalar_one()
    add("decision_deleted_count", float(deleted_count))

    avg_score = db.execute(select(func.avg(usage_base.c.value_number)).where(usage_base.c.event_type == "decision_scored")).scalar_one()
    add("decision_avg_score", float(avg_score or 0.0), unit="score")

    below_threshold_count = db.execute(select(func.count()).select_from(usage_base).where(usage_base.c.event_type == "decision_below_threshold")).scalar_one()
    add("decisions_below_threshold_count", float(below_threshold_count))

    goal_updates_count = db.execute(select(func.count()).select_from(usage_base).where(usage_base.c.event_type.in_(["goal_created", "goal_updated", "goal_deleted"]))).scalar_one()
    add("goal_updates_count", float(goal_updates_count))

    question_query = select(func.count()).select_from(AgentQuestion).where(
        AgentQuestion.family_id == family_id,
        AgentQuestion.status.in_(sorted(ACTIVE_QUESTION_STATUSES)),
    )
    add("question_queue_open_count", float(db.execute(question_query).scalar_one()))

    question_resolved_query = select(func.count()).select_from(AgentQuestionEvent).where(
        AgentQuestionEvent.family_id == family_id,
        AgentQuestionEvent.event_type == "resolved",
    )
    if start_at:
        question_resolved_query = question_resolved_query.where(AgentQuestionEvent.created_at >= start_at)
    if end_at:
        question_resolved_query = question_resolved_query.where(AgentQuestionEvent.created_at <= end_at)
    add("question_queue_resolved_count", float(db.execute(question_resolved_query).scalar_one()))

    task_created_count = db.execute(select(func.count()).select_from(usage_base).where(usage_base.c.event_type == "task_created")).scalar_one()
    add("task_created_count", float(task_created_count))

    task_completion_count = db.execute(select(func.count()).select_from(usage_base).where(usage_base.c.event_type == "task_completed")).scalar_one()
    add("task_completion_count", float(task_completion_count))

    task_deleted_count = db.execute(select(func.count()).select_from(usage_base).where(usage_base.c.event_type == "task_deleted")).scalar_one()
    add("task_deleted_count", float(task_deleted_count))

    file_indexed_count = db.execute(select(func.count()).select_from(usage_base).where(usage_base.c.event_type == "file_indexed")).scalar_one()
    add("file_indexed_count", float(file_indexed_count))

    file_auto_filed_count = db.execute(select(func.count()).select_from(usage_base).where(usage_base.c.event_type == "file_auto_filed")).scalar_one()
    add("file_auto_filed_count", float(file_auto_filed_count))

    file_review_needed_count = db.execute(select(func.count()).select_from(usage_base).where(usage_base.c.event_type == "file_review_needed")).scalar_one()
    add("file_review_needed_count", float(file_review_needed_count))

    file_delete_requested_count = db.execute(select(func.count()).select_from(usage_base).where(usage_base.c.event_type == "file_delete_requested")).scalar_one()
    add("file_delete_requested_count", float(file_delete_requested_count))

    file_deleted_count = db.execute(select(func.count()).select_from(usage_base).where(usage_base.c.event_type == "file_deleted")).scalar_one()
    add("file_deleted_count", float(file_deleted_count))

    file_inbox_backlog_count = db.execute(select(func.count()).select_from(usage_base).where(usage_base.c.event_type == "file_inbox_backlog")).scalar_one()
    add("file_inbox_backlog_count", float(file_inbox_backlog_count))

    file_unclassified_count = db.execute(select(func.count()).select_from(usage_base).where(usage_base.c.event_type == "file_unclassified")).scalar_one()
    add("file_unclassified_count", float(file_unclassified_count))

    if keys.intersection({"task_open_count", "task_overdue_count", "task_load_total", "task_load_by_member", "task_load_by_project", "project_count", "stale_task_count"}):
        try:
            task_snapshot = latest_task_health_snapshot()
        except Exception:
            task_snapshot = None
        if task_snapshot is not None:
            overview = task_snapshot.get("overview", {})
            add("task_open_count", float(overview.get("total_open_tasks") or 0))
            add("task_overdue_count", float(overview.get("overdue_tasks") or 0))
            add("task_load_total", float(overview.get("total_open_tasks") or 0))
            add(
                "task_load_by_member",
                float(sum(float(item.get("open_tasks") or 0) for item in task_snapshot.get("member_load", []))),
                metadata={"items": task_snapshot.get("member_load", [])},
            )
            add(
                "task_load_by_project",
                float(sum(float(item.get("open_tasks") or 0) for item in task_snapshot.get("project_load", []))),
                metadata={"items": task_snapshot.get("project_load", [])},
            )
            add("project_count", float(len(task_snapshot.get("projects", []))))
            add("stale_task_count", float(overview.get("stale_tasks") or 0))

    now = _utcnow()
    due_soon_query = (
        select(func.count())
        .select_from(RoadmapItem)
        .join(Decision, Decision.id == RoadmapItem.decision_id)
        .where(
            Decision.family_id == family_id,
            RoadmapItem.status.not_in(["Done", "Removed", "Archived"]),
            RoadmapItem.end_date.is_not(None),
            RoadmapItem.end_date <= now.date(),
        )
    )
    add("roadmap_due_soon_backlog_count", float(db.execute(due_soon_query).scalar_one()))

    return out


def get_playback_timeline(
    db: Session,
    *,
    family_id: int,
    domain: str | None,
    event_types: list[str],
    start_at: datetime | None,
    end_at: datetime | None,
    limit: int,
) -> list[dict[str, Any]]:
    query = select(AgentPlaybackEvent).where(AgentPlaybackEvent.family_id == family_id)
    if domain:
        query = query.where(AgentPlaybackEvent.domain == domain)
    if event_types:
        query = query.where(AgentPlaybackEvent.event_type.in_(event_types))
    if start_at:
        query = query.where(AgentPlaybackEvent.created_at >= start_at)
    if end_at:
        query = query.where(AgentPlaybackEvent.created_at <= end_at)
    items = db.execute(query.order_by(AgentPlaybackEvent.created_at.desc()).limit(limit)).scalars().all()
    return [_playback_event_response(item) for item in items]


def latest_decision_health_snapshot(db: Session, *, family_id: int) -> dict[str, Any]:
    decisions = db.execute(select(Decision).where(Decision.family_id == family_id)).scalars().all()
    goals = db.execute(select(Goal).where(Goal.family_id == family_id)).scalars().all()
    roadmap_rows = db.execute(select(RoadmapItem, Decision).join(Decision, Decision.id == RoadmapItem.decision_id).where(Decision.family_id == family_id)).all()

    score_totals: dict[int, float] = {}
    score_counts: dict[int, int] = {}
    score_rows = db.execute(
        select(DecisionScore.decision_id, DecisionScore.score_1_to_5).join(Decision, Decision.id == DecisionScore.decision_id).where(
            Decision.family_id == family_id,
            Decision.version == DecisionScore.version,
        )
    ).all()
    for decision_id, score in score_rows:
        score_totals[int(decision_id)] = score_totals.get(int(decision_id), 0.0) + float(score)
        score_counts[int(decision_id)] = score_counts.get(int(decision_id), 0) + 1

    policy = db.execute(select(BudgetPolicy).where(BudgetPolicy.family_id == family_id)).scalar_one_or_none()

    return {
        "budget_policy": {
            "threshold_1_to_5": float(policy.threshold_1_to_5) if policy is not None else 4.0,
            "period_days": int(policy.period_days) if policy is not None else 90,
            "default_allowance": int(policy.default_allowance) if policy is not None else 2,
        },
        "decisions": [
            {
                "id": item.id,
                "title": item.title,
                "status": item.status.value,
                "target_date": item.target_date.isoformat() if item.target_date else None,
                "urgency": item.urgency,
                "score_average": round(score_totals[item.id] / score_counts[item.id], 3) if score_counts.get(item.id) else None,
                "version": item.version,
            }
            for item in decisions
        ],
        "goals": [
            {
                "id": goal.id,
                "name": goal.name,
                "weight": goal.weight,
                "active": goal.active,
            }
            for goal in goals
        ],
        "roadmap_items": [
            {
                "id": item.id,
                "decision_id": item.decision_id,
                "decision_title": decision.title,
                "status": item.status,
                "bucket": item.bucket,
                "start_date": item.start_date.isoformat() if item.start_date else None,
                "end_date": item.end_date.isoformat() if item.end_date else None,
            }
            for item, decision in roadmap_rows
        ],
    }
