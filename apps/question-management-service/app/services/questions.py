from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from agents.common.family_events import (
    build_event,
    diff_field_paths,
    make_privacy,
    new_correlation_id,
    publish_event as publish_family_event,
    snippet_fields,
)
from app.core.config import settings
from app.models.questions import QuestionDeliveryAttempt, QuestionEngagementWindow, QuestionEvent, QuestionRecord

ACTIVE_QUESTION_STATUSES = {"pending", "asked", "answered_partial"}
CLAIMABLE_QUESTION_STATUSES = {"pending", "answered_partial"}
QUESTION_NOISE_RE = re.compile(r"\b(test|dummy|placeholder|sample|do not use|ignore me|smoke test|system task)\b", re.IGNORECASE)
TASK_AUTO_AGENTS = {"TaskAgent", "TasksAgent"}
URGENCY_PRIORITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}
QUESTION_SUBJECT_PERSON_KEYS = (
    "subject_person_id",
    "target_person_id",
    "owner_person_id",
    "person_id",
    "actor_person_id",
)

logger = logging.getLogger("family_cloud.question_service")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_local_hour(value: datetime, timezone_name: str | None = None) -> int:
    zone = ZoneInfo(timezone_name or settings.question_default_timezone)
    return value.astimezone(zone).hour


def _sanitize_due_date(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.year < 1970:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_category(category: str | None, topic_type: str | None) -> str:
    value = (category or topic_type or "generic").strip().lower()
    return re.sub(r"[^a-z0-9_-]+", "_", value)[:64] or "generic"


def _question_context(question: QuestionRecord) -> dict[str, Any]:
    context = dict(question.context_json or {})
    return context if isinstance(context, dict) else {}


def _artifact_refs(question: QuestionRecord) -> list[dict[str, Any]]:
    refs = list(question.artifact_refs_json or [])
    return [item for item in refs if isinstance(item, dict)]


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()


def _nonempty_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


def _question_subject_person_id(question: QuestionRecord) -> str | None:
    context = _question_context(question)
    for key in QUESTION_SUBJECT_PERSON_KEYS:
        value = context.get(key)
        if value not in (None, ""):
            return str(value)
    person_ids = context.get("person_ids")
    if isinstance(person_ids, list):
        for value in person_ids:
            if value not in (None, ""):
                return str(value)
    return None


def _question_state(question: QuestionRecord) -> dict[str, Any]:
    return {
        "domain": question.domain,
        "source_agent": question.source_agent,
        "topic": question.topic,
        "category": question.category,
        "summary": question.summary,
        "prompt": question.prompt,
        "urgency": question.urgency,
        "status": question.status,
        "expires_at": _isoformat(question.expires_at),
        "due_at": _isoformat(question.due_at),
        "last_asked_at": _isoformat(question.last_asked_at),
        "answered_at": _isoformat(question.answered_at),
        "answer_text": question.answer_text,
        "answer_sufficiency_state": question.answer_sufficiency_state,
        "asked_count": int(question.asked_count or 0),
        "last_delivery_channel": question.last_delivery_channel,
        "last_delivery_agent": question.last_delivery_agent,
        "context": _question_context(question),
        "artifact_refs": _artifact_refs(question),
        "dedupe_key": question.dedupe_key,
    }


def _question_delivery_summary(
    question: QuestionRecord,
    *,
    attempt: QuestionDeliveryAttempt | None = None,
) -> dict[str, Any]:
    delivery = {
        "delivery_agent": attempt.agent_id if attempt is not None else question.last_delivery_agent,
        "delivery_channel": attempt.channel if attempt is not None else question.last_delivery_channel,
        "sent_at": _isoformat(attempt.sent_at) if attempt is not None else _isoformat(question.last_asked_at),
        "responded_at": _isoformat(attempt.responded_at) if attempt is not None else _isoformat(question.answered_at),
        "outcome": attempt.outcome if attempt is not None else None,
    }
    if attempt is not None and attempt.claim_token:
        delivery["claim_token"] = attempt.claim_token
    if attempt is not None and isinstance(attempt.payload_json, dict) and attempt.payload_json:
        delivery["delivery_context_keys"] = sorted(str(key) for key in attempt.payload_json)
    return _nonempty_dict(delivery)


def _question_event_payload(
    question: QuestionRecord,
    *,
    changed_fields: list[str] | None = None,
    resolution_note: str | None = None,
    attempt: QuestionDeliveryAttempt | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = _question_context(question)
    payload: dict[str, Any] = {
        "question_id": question.id,
        "origin_domain": question.domain,
        "source_agent": question.source_agent,
        "category": question.category,
        "urgency": question.urgency,
        "status": question.status,
        "answer_sufficiency_state": question.answer_sufficiency_state,
        "asked_count": int(question.asked_count or 0),
        "due_at": _isoformat(question.due_at),
        "expires_at": _isoformat(question.expires_at),
        "last_asked_at": _isoformat(question.last_asked_at),
        "answered_at": _isoformat(question.answered_at),
        "dedupe_key": question.dedupe_key,
        "artifact_refs": _artifact_refs(question),
        "context_keys": sorted(str(key) for key in context),
    }
    payload.update(snippet_fields("topic", question.topic))
    payload.update(snippet_fields("summary", question.summary))
    payload.update(snippet_fields("prompt", question.prompt))
    payload.update(snippet_fields("answer_text", question.answer_text))
    payload.update(snippet_fields("resolution_note", resolution_note))
    payload["title"] = payload.get("topic_snippet") or payload.get("summary_snippet") or f"Question {question.id}"
    if changed_fields:
        payload["changed_fields"] = changed_fields
    delivery = _question_delivery_summary(question, attempt=attempt)
    if delivery:
        payload["delivery"] = delivery
    if question.current_claim_token and question.current_claim_expires_at:
        payload["claim"] = _nonempty_dict(
            {
                "claim_token": question.current_claim_token,
                "claim_agent": question.current_claim_agent,
                "claim_channel": question.current_claim_channel,
                "claimed_at": _isoformat(question.current_claimed_at),
                "expires_at": _isoformat(question.current_claim_expires_at),
            }
        )
    if extra_payload:
        payload.update({key: value for key, value in extra_payload.items() if value is not None})
    return payload


def _publish_question_event(
    *,
    question: QuestionRecord,
    actor: str,
    event_type: str,
    payload: dict[str, Any],
    correlation_id: str | None = None,
    source_channel: str | None = None,
    occurred_at: datetime | None = None,
) -> None:
    try:
        subject_person_id = _question_subject_person_id(question)
        event = build_event(
            family_id=question.family_id,
            domain="question",
            event_type=event_type,
            actor={
                "actor_type": "system" if actor.startswith("system") else "user",
                "actor_id": actor,
            },
            subject={
                "subject_type": "question",
                "subject_id": question.id,
                "person_id": subject_person_id,
            },
            payload=payload,
            source={
                "agent_id": "QuestionService",
                "runtime": "backend",
                "channel": source_channel,
            },
            privacy=make_privacy(
                contains_pii=True,
                contains_child_data=bool(subject_person_id),
                contains_free_text=any(
                    field in payload
                    for field in (
                        "topic_snippet",
                        "summary_snippet",
                        "prompt_snippet",
                        "answer_text_snippet",
                        "resolution_note_snippet",
                    )
                ),
            ),
            tags=["question", question.domain, question.category, question.status],
            correlation_id=correlation_id,
            occurred_at=occurred_at or _utcnow(),
        )
        publish_family_event(event)
    except Exception:
        logger.exception("Failed to publish canonical question event question_id=%s event_type=%s", question.id, event_type)


def _publish_question_summary_event(
    *,
    family_id: int,
    actor: str,
    event_type: str,
    subject_id: str,
    payload: dict[str, Any],
    correlation_id: str | None = None,
    source_channel: str | None = None,
) -> None:
    try:
        event = build_event(
            family_id=family_id,
            domain="question",
            event_type=event_type,
            actor={
                "actor_type": "system" if actor.startswith("system") else "user",
                "actor_id": actor,
            },
            subject={"subject_type": "question", "subject_id": subject_id},
            payload=payload,
            source={
                "agent_id": "QuestionService",
                "runtime": "backend",
                "channel": source_channel,
            },
            privacy=make_privacy(contains_pii=False, contains_free_text=False),
            tags=["question", "summary"],
            correlation_id=correlation_id,
        )
        publish_family_event(event)
    except Exception:
        logger.exception("Failed to publish canonical question summary event family_id=%s event_type=%s", family_id, event_type)


def _claim_payload(question: QuestionRecord) -> dict[str, Any] | None:
    if not question.current_claim_token or not question.current_claim_expires_at:
        return None
    if question.current_claim_expires_at <= _utcnow():
        return None
    return {
        "token": question.current_claim_token,
        "agent": question.current_claim_agent,
        "channel": question.current_claim_channel,
        "claimed_at": question.current_claimed_at,
        "expires_at": question.current_claim_expires_at,
    }


def question_response(question: QuestionRecord) -> dict[str, Any]:
    return {
        "id": question.id,
        "family_id": question.family_id,
        "domain": question.domain,
        "source_agent": question.source_agent,
        "topic": question.topic,
        "category": question.category,
        "topic_type": question.category,
        "summary": question.summary,
        "prompt": question.prompt,
        "urgency": question.urgency,
        "status": question.status,
        "created_at": question.created_at,
        "updated_at": question.updated_at,
        "expires_at": question.expires_at,
        "due_at": question.due_at,
        "last_asked_at": question.last_asked_at,
        "answered_at": question.answered_at,
        "answer_text": question.answer_text,
        "answer_sufficiency_state": question.answer_sufficiency_state,
        "asked_count": question.asked_count,
        "last_delivery_channel": question.last_delivery_channel,
        "last_delivery_agent": question.last_delivery_agent,
        "current_claim": _claim_payload(question),
        "context": _question_context(question),
        "artifact_refs": _artifact_refs(question),
        "dedupe_key": question.dedupe_key,
    }


def event_response(event: QuestionEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "question_id": event.question_id,
        "family_id": event.family_id,
        "actor": event.actor,
        "event_type": event.event_type,
        "payload": dict(event.payload_json or {}),
        "created_at": event.created_at,
    }


def attempt_response(attempt: QuestionDeliveryAttempt) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "question_id": attempt.question_id,
        "family_id": attempt.family_id,
        "claim_token": attempt.claim_token,
        "agent_id": attempt.agent_id,
        "channel": attempt.channel,
        "sent_at": attempt.sent_at,
        "responded_at": attempt.responded_at,
        "outcome": attempt.outcome,
        "payload": dict(attempt.payload_json or {}),
        "created_at": attempt.created_at,
    }


def append_question_event(
    db: Session,
    *,
    question_id: str,
    family_id: int,
    actor: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> QuestionEvent:
    event = QuestionEvent(
        question_id=question_id,
        family_id=family_id,
        actor=actor,
        event_type=event_type,
        payload_json=payload or {},
    )
    db.add(event)
    db.flush()
    return event


def _question_blob(*, topic: str, summary: str, prompt: str, context: dict[str, Any] | None) -> str:
    return "\n".join(
        [
            topic,
            summary,
            prompt,
            " ".join(f"{key}={value}" for key, value in (context or {}).items()),
        ]
    )


def _suppression_reason(
    db: Session,
    *,
    family_id: int,
    domain: str,
    source_agent: str,
    topic: str,
    summary: str,
    prompt: str,
    urgency: str,
    context: dict[str, Any] | None,
) -> str | None:
    blob = _question_blob(topic=topic, summary=summary, prompt=prompt, context=context)
    if QUESTION_NOISE_RE.search(blob):
        return "noise_filtered"
    if domain == "task" and source_agent in TASK_AUTO_AGENTS and urgency != "critical":
        active_count = db.execute(
            select(func.count()).select_from(QuestionRecord).where(
                QuestionRecord.family_id == family_id,
                QuestionRecord.domain == "task",
                QuestionRecord.status.in_(sorted(ACTIVE_QUESTION_STATUSES)),
            )
        ).scalar_one()
        if int(active_count or 0) >= settings.question_task_auto_cap:
            return "task_auto_cap_reached"
    return None


def _artifact_identity(artifact_refs: list[dict[str, Any]] | None) -> tuple[str | None, str | None]:
    for ref in artifact_refs or []:
        if not isinstance(ref, dict):
            continue
        ref_type = str(ref.get("type") or "").strip().lower()
        ref_value = ref.get("id")
        if ref_value is None:
            ref_value = ref.get("path")
        if ref_type and ref_value not in (None, ""):
            return ref_type, str(ref_value)
    return None, None


def _dismiss_superseded_questions(
    db: Session,
    *,
    question: QuestionRecord,
    actor: str,
    correlation_id: str | None = None,
) -> None:
    ref_type, ref_value = _artifact_identity(_artifact_refs(question))
    if not ref_type or not ref_value:
        return
    candidates = db.execute(
        select(QuestionRecord).where(
            QuestionRecord.family_id == question.family_id,
            QuestionRecord.domain == question.domain,
            QuestionRecord.category == question.category,
            QuestionRecord.status.in_(sorted(ACTIVE_QUESTION_STATUSES)),
            QuestionRecord.id != question.id,
        )
    ).scalars().all()
    for candidate in candidates:
        other_type, other_value = _artifact_identity(_artifact_refs(candidate))
        if other_type != ref_type or other_value != ref_value:
            continue
        candidate.status = "dismissed"
        candidate.updated_at = _utcnow()
        candidate.current_claim_token = None
        candidate.current_claim_agent = None
        candidate.current_claim_channel = None
        candidate.current_claimed_at = None
        candidate.current_claim_expires_at = None
        append_question_event(
            db,
            question_id=candidate.id,
            family_id=candidate.family_id,
            actor=actor,
            event_type="dismissed",
            payload={"reason": "superseded_by_newer_question", "replacement_question_id": question.id},
        )
        _publish_question_event(
            question=candidate,
            actor=actor,
            event_type="question.dismissed",
            correlation_id=correlation_id,
            payload=_question_event_payload(
                candidate,
                extra_payload={
                    "dismissal_reason": "superseded_by_newer_question",
                    "replacement_question_id": question.id,
                },
            ),
        )


def create_or_update_question(
    db: Session,
    *,
    family_id: int,
    domain: str,
    source_agent: str,
    topic: str | None,
    category: str | None,
    topic_type: str | None,
    summary: str,
    prompt: str,
    urgency: str,
    actor: str,
    dedupe_key: str,
    expires_at: datetime | None = None,
    due_at: datetime | None = None,
    answer_sufficiency_state: str = "unknown",
    context: dict[str, Any] | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_category = _normalize_category(category, topic_type)
    normalized_topic = (topic or summary).strip()[:255] or normalized_category.replace("_", " ").title()
    clean_due_at = _sanitize_due_date(due_at)
    clean_expires_at = _sanitize_due_date(expires_at)
    suppression_reason = _suppression_reason(
        db,
        family_id=family_id,
        domain=domain,
        source_agent=source_agent,
        topic=normalized_topic,
        summary=summary,
        prompt=prompt,
        urgency=urgency,
        context=context,
    )
    if suppression_reason:
        return {"question": None, "event": None, "suppressed": True, "suppression_reason": suppression_reason}

    now = _utcnow()
    question = db.execute(
        select(QuestionRecord).where(
            QuestionRecord.family_id == family_id,
            QuestionRecord.domain == domain,
            QuestionRecord.dedupe_key == dedupe_key,
        )
    ).scalar_one_or_none()

    correlation_id = new_correlation_id()
    created = False
    payload_context = context or {}
    payload_refs = [item for item in (artifact_refs or []) if isinstance(item, dict)]
    before_state: dict[str, Any] | None = None

    if question is None:
        question = QuestionRecord(
            id=str(uuid.uuid4()),
            family_id=family_id,
            domain=domain,
            source_agent=source_agent,
            topic=normalized_topic,
            category=normalized_category,
            summary=summary,
            prompt=prompt,
            urgency=urgency,
            status="pending",
            created_at=now,
            updated_at=now,
            expires_at=clean_expires_at,
            due_at=clean_due_at,
            answer_sufficiency_state=answer_sufficiency_state,
            context_json=payload_context,
            artifact_refs_json=payload_refs,
            dedupe_key=dedupe_key,
        )
        db.add(question)
        db.flush()
        created = True
    else:
        before_state = _question_state(question)
        current_context = _question_context(question)
        current_context.update(payload_context)
        question.source_agent = source_agent
        question.topic = normalized_topic
        question.category = normalized_category
        question.summary = summary
        question.prompt = prompt
        question.urgency = urgency
        question.updated_at = now
        question.expires_at = clean_expires_at
        question.due_at = clean_due_at
        question.answer_sufficiency_state = answer_sufficiency_state
        question.context_json = current_context
        question.artifact_refs_json = payload_refs
        if question.status not in ACTIVE_QUESTION_STATUSES:
            question.status = "pending"
        db.flush()

    _dismiss_superseded_questions(db, question=question, actor=actor, correlation_id=correlation_id)
    changed_fields = diff_field_paths(before_state, _question_state(question)) if before_state is not None else [
        "domain",
        "source_agent",
        "topic",
        "category",
        "summary",
        "prompt",
        "urgency",
        "status",
        "expires_at",
        "due_at",
        "answer_sufficiency_state",
        "context",
        "artifact_refs",
        "dedupe_key",
    ]
    event = append_question_event(
        db,
        question_id=question.id,
        family_id=family_id,
        actor=actor,
        event_type="created" if created else "updated",
        payload={
            "topic": normalized_topic,
            "urgency": urgency,
            "category": normalized_category,
            "changed_fields": changed_fields,
        },
    )
    _publish_question_event(
        question=question,
        actor=actor,
        event_type="question.created" if created else "question.updated",
        correlation_id=correlation_id,
        payload=_question_event_payload(
            question,
            changed_fields=changed_fields,
            extra_payload={"event_id": event.id},
        ),
    )
    return {"question": question_response(question), "event": event_response(event), "suppressed": False, "suppression_reason": None}


def list_questions(
    db: Session,
    *,
    family_id: int,
    domain: str | None = None,
    category: str | None = None,
    status: str | None = None,
    urgency: str | None = None,
    source_agent: str | None = None,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    query = select(QuestionRecord).where(QuestionRecord.family_id == family_id)
    if domain:
        query = query.where(QuestionRecord.domain == domain)
    if category:
        query = query.where(QuestionRecord.category == _normalize_category(category, None))
    if status:
        query = query.where(QuestionRecord.status == status)
    elif not include_inactive:
        query = query.where(QuestionRecord.status.in_(sorted(ACTIVE_QUESTION_STATUSES)))
    if urgency:
        query = query.where(QuestionRecord.urgency == urgency)
    if source_agent:
        query = query.where(QuestionRecord.source_agent == source_agent)
    items = db.execute(query).scalars().all()
    ranked = sorted(
        items,
        key=lambda item: (
            URGENCY_PRIORITY.get(item.urgency, 99),
            item.due_at is None,
            item.due_at or datetime.max.replace(tzinfo=UTC),
            -item.updated_at.timestamp(),
        ),
    )
    return [question_response(item) for item in ranked]


def get_question(db: Session, question_id: str) -> QuestionRecord | None:
    return db.get(QuestionRecord, question_id)


def update_question(
    db: Session,
    *,
    question: QuestionRecord,
    actor: str,
    topic: str | None = None,
    summary: str | None = None,
    prompt: str | None = None,
    urgency: str | None = None,
    category: str | None = None,
    topic_type: str | None = None,
    status: str | None = None,
    expires_at: datetime | None = None,
    due_at: datetime | None = None,
    answer_sufficiency_state: str | None = None,
    context_patch: dict[str, Any] | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    before_state = _question_state(question)
    if topic is not None:
        question.topic = topic.strip()[:255] or question.topic
    if summary is not None:
        question.summary = summary
    if prompt is not None:
        question.prompt = prompt
    if urgency is not None:
        question.urgency = urgency
    if category is not None or topic_type is not None:
        question.category = _normalize_category(category, topic_type)
    if status is not None:
        question.status = status
    if expires_at is not None:
        question.expires_at = _sanitize_due_date(expires_at)
    if due_at is not None:
        question.due_at = _sanitize_due_date(due_at)
    if answer_sufficiency_state is not None:
        question.answer_sufficiency_state = answer_sufficiency_state
    if context_patch:
        context = _question_context(question)
        context.update(context_patch)
        question.context_json = context
    if artifact_refs is not None:
        question.artifact_refs_json = [item for item in artifact_refs if isinstance(item, dict)]
    question.updated_at = _utcnow()
    db.flush()
    changed_fields = diff_field_paths(before_state, _question_state(question))
    correlation_id = new_correlation_id()
    event = append_question_event(
        db,
        question_id=question.id,
        family_id=question.family_id,
        actor=actor,
        event_type="updated",
        payload={
            "status": question.status,
            "answer_sufficiency_state": question.answer_sufficiency_state,
            "changed_fields": changed_fields,
        },
    )
    _publish_question_event(
        question=question,
        actor=actor,
        event_type="question.updated",
        correlation_id=correlation_id,
        payload=_question_event_payload(
            question,
            changed_fields=changed_fields,
            extra_payload={"event_id": event.id},
        ),
    )
    return {"question": question_response(question), "event": event_response(event)}


def release_expired_claims(db: Session, *, family_id: int | None = None, actor: str = "system") -> int:
    now = _utcnow()
    correlation_id = new_correlation_id()
    query = select(QuestionRecord).where(
        QuestionRecord.current_claim_token.is_not(None),
        QuestionRecord.current_claim_expires_at.is_not(None),
        QuestionRecord.current_claim_expires_at < now,
    )
    if family_id is not None:
        query = query.where(QuestionRecord.family_id == family_id)
    items = db.execute(query).scalars().all()
    for item in items:
        token = item.current_claim_token
        item.current_claim_token = None
        item.current_claim_agent = None
        item.current_claim_channel = None
        item.current_claimed_at = None
        item.current_claim_expires_at = None
        item.updated_at = now
        append_question_event(
            db,
            question_id=item.id,
            family_id=item.family_id,
            actor=actor,
            event_type="claim_released",
            payload={"reason": "lease_expired", "claim_token": token},
        )
        _publish_question_event(
            question=item,
            actor=actor,
            event_type="question.claim_released",
            correlation_id=correlation_id,
            payload=_question_event_payload(
                item,
                extra_payload={"release_reason": "lease_expired", "claim_token": token},
            ),
        )
    db.flush()
    return len(items)


def expire_questions(db: Session, *, family_id: int | None = None, actor: str = "system") -> int:
    now = _utcnow()
    correlation_id = new_correlation_id()
    query = select(QuestionRecord).where(
        QuestionRecord.status.in_(sorted(ACTIVE_QUESTION_STATUSES)),
        QuestionRecord.expires_at.is_not(None),
        QuestionRecord.expires_at < now,
    )
    if family_id is not None:
        query = query.where(QuestionRecord.family_id == family_id)
    items = db.execute(query).scalars().all()
    for item in items:
        item.status = "expired"
        item.updated_at = now
        item.current_claim_token = None
        item.current_claim_agent = None
        item.current_claim_channel = None
        item.current_claimed_at = None
        item.current_claim_expires_at = None
        append_question_event(
            db,
            question_id=item.id,
            family_id=item.family_id,
            actor=actor,
            event_type="expired",
            payload={"expired_at": now.isoformat()},
        )
        _publish_question_event(
            question=item,
            actor=actor,
            event_type="question.expired",
            correlation_id=correlation_id,
            payload=_question_event_payload(
                item,
                extra_payload={"expired_at": now.isoformat()},
            ),
        )
    db.flush()
    return len(items)


def _requeue_stale_asked_questions(db: Session, *, actor: str = "system") -> int:
    threshold = _utcnow() - timedelta(hours=settings.question_requeue_stale_asked_hours)
    correlation_id = new_correlation_id()
    items = db.execute(
        select(QuestionRecord).where(
            QuestionRecord.status == "asked",
            QuestionRecord.answered_at.is_(None),
            QuestionRecord.last_asked_at.is_not(None),
            QuestionRecord.last_asked_at < threshold,
        )
    ).scalars().all()
    for item in items:
        item.status = "pending"
        item.updated_at = _utcnow()
        append_question_event(
            db,
            question_id=item.id,
            family_id=item.family_id,
            actor=actor,
            event_type="requeued",
            payload={"reason": "stale_asked_without_response"},
        )
        _publish_question_event(
            question=item,
            actor=actor,
            event_type="question.requeued",
            correlation_id=correlation_id,
            payload=_question_event_payload(
                item,
                extra_payload={"requeue_reason": "stale_asked_without_response"},
            ),
        )
    db.flush()
    return len(items)


def cleanup_question_backlog(db: Session, *, actor: str = "system") -> dict[str, int]:
    now = _utcnow()
    correlation_id = new_correlation_id()
    stale_pending_cutoff = now - timedelta(days=settings.question_stale_pending_days)
    stale_pending = db.execute(
        select(QuestionRecord).where(
            QuestionRecord.status == "pending",
            QuestionRecord.updated_at < stale_pending_cutoff,
        )
    ).scalars().all()
    for item in stale_pending:
        item.status = "dismissed"
        item.updated_at = now
        append_question_event(
            db,
            question_id=item.id,
            family_id=item.family_id,
            actor=actor,
            event_type="dismissed",
            payload={"reason": "stale_pending_backlog_cleanup"},
        )
        _publish_question_event(
            question=item,
            actor=actor,
            event_type="question.dismissed",
            correlation_id=correlation_id,
            payload=_question_event_payload(
                item,
                extra_payload={"dismissal_reason": "stale_pending_backlog_cleanup"},
            ),
        )
    db.flush()
    return {
        "released_claims": release_expired_claims(db, actor=actor),
        "expired": expire_questions(db, actor=actor),
        "requeued": _requeue_stale_asked_questions(db, actor=actor),
        "dismissed_stale_pending": len(stale_pending),
    }


def _delivery_window_ok(
    db: Session,
    *,
    family_id: int,
    agent_id: str,
    channel: str,
    timezone_name: str,
    now: datetime,
    force: bool,
) -> tuple[bool, str | None]:
    if force:
        return True, None
    current_hour = _safe_local_hour(now, timezone_name)
    quiet_start = settings.question_quiet_hours_start
    quiet_end = settings.question_quiet_hours_end
    in_quiet_hours = current_hour >= quiet_start or current_hour < quiet_end if quiet_start > quiet_end else quiet_start <= current_hour < quiet_end
    if in_quiet_hours:
        return False, "quiet_hours"

    latest_attempt = db.execute(
        select(QuestionDeliveryAttempt)
        .where(
            QuestionDeliveryAttempt.family_id == family_id,
            QuestionDeliveryAttempt.channel == channel,
        )
        .order_by(QuestionDeliveryAttempt.sent_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest_attempt and latest_attempt.sent_at >= now - timedelta(minutes=settings.question_delivery_cooldown_minutes):
        return False, "recent_outbound_question"

    latest_answer = db.execute(
        select(QuestionRecord)
        .where(
            QuestionRecord.family_id == family_id,
            QuestionRecord.answered_at.is_not(None),
        )
        .order_by(QuestionRecord.answered_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest_answer and latest_answer.answered_at and latest_answer.answered_at >= now - timedelta(minutes=settings.question_post_answer_cooldown_minutes):
        return False, "recent_user_response"

    windows = db.execute(
        select(QuestionEngagementWindow).where(
            QuestionEngagementWindow.family_id == family_id,
            QuestionEngagementWindow.channel == channel,
            QuestionEngagementWindow.agent_id.in_([agent_id, "*"]),
        )
    ).scalars().all()
    if not windows:
        if settings.question_daytime_start <= current_hour <= settings.question_daytime_end:
            return True, None
        return False, "outside_fallback_daytime_window"

    enough_history = max((window.attempt_count for window in windows), default=0) >= settings.question_learning_min_attempts
    if not enough_history:
        if settings.question_daytime_start <= current_hour <= settings.question_daytime_end:
            return True, None
        return False, "outside_fallback_daytime_window"

    ranked_hours = [window.local_hour for window in sorted(windows, key=lambda item: (-item.score, item.local_hour))[:3]]
    if any(min((current_hour - hour) % 24, (hour - current_hour) % 24) <= 1 for hour in ranked_hours):
        return True, None
    return False, "engagement_window_not_open"


def _question_outstanding_in_channel(db: Session, *, family_id: int, channel: str) -> bool:
    count = db.execute(
        select(func.count()).select_from(QuestionRecord).where(
            QuestionRecord.family_id == family_id,
            QuestionRecord.status == "asked",
            QuestionRecord.last_delivery_channel == channel,
            QuestionRecord.answered_at.is_(None),
        )
    ).scalar_one()
    return bool(count)


def _merge_key(question: QuestionRecord) -> str | None:
    context = _question_context(question)
    for key in ("project_id", "project", "bucket", "learner_id", "group_key"):
        value = context.get(key)
        if value not in (None, ""):
            return f"context:{key}:{value}"
    ref_type, ref_value = _artifact_identity(_artifact_refs(question))
    if ref_type and ref_value:
        return f"artifact:{ref_type}:{ref_value}"
    return None


def claim_next_questions(
    db: Session,
    *,
    family_id: int,
    agent_id: str,
    channel: str,
    actor: str,
    lease_seconds: int | None = None,
    allow_merge: bool = True,
    force: bool = False,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    now = _utcnow()
    correlation_id = new_correlation_id()
    expire_questions(db, family_id=family_id, actor="system")
    release_expired_claims(db, family_id=family_id, actor="system")

    if _question_outstanding_in_channel(db, family_id=family_id, channel=channel):
        return {"items": [], "claim_token": None, "eligible": False, "reason": "awaiting_reply"}

    timing_ok, timing_reason = _delivery_window_ok(
        db,
        family_id=family_id,
        agent_id=agent_id,
        channel=channel,
        timezone_name=timezone_name or settings.question_default_timezone,
        now=now,
        force=force,
    )
    if not timing_ok:
        return {"items": [], "claim_token": None, "eligible": False, "reason": timing_reason}

    query = select(QuestionRecord).where(
        QuestionRecord.family_id == family_id,
        QuestionRecord.status.in_(sorted(CLAIMABLE_QUESTION_STATUSES)),
        or_(QuestionRecord.current_claim_token.is_(None), QuestionRecord.current_claim_expires_at < now),
    )
    candidates = db.execute(query).scalars().all()
    candidates = [item for item in candidates if item.expires_at is None or item.expires_at >= now]
    candidates = sorted(
        candidates,
        key=lambda item: (
            URGENCY_PRIORITY.get(item.urgency, 99),
            item.due_at is None,
            item.due_at or datetime.max.replace(tzinfo=UTC),
            item.asked_count,
            -item.updated_at.timestamp(),
        ),
    )
    if not candidates:
        return {"items": [], "claim_token": None, "eligible": False, "reason": "no_claimable_questions"}

    chosen = [candidates[0]]
    merge_key = _merge_key(candidates[0])
    if allow_merge and merge_key and settings.question_merge_limit > 1:
        for candidate in candidates[1:]:
            if len(chosen) >= settings.question_merge_limit:
                break
            if _merge_key(candidate) == merge_key and candidate.category == candidates[0].category:
                chosen.append(candidate)

    claim_token = str(uuid.uuid4())
    expires_at = now + timedelta(seconds=lease_seconds or settings.question_claim_lease_seconds)
    for item in chosen:
        item.current_claim_token = claim_token
        item.current_claim_agent = agent_id
        item.current_claim_channel = channel
        item.current_claimed_at = now
        item.current_claim_expires_at = expires_at
        item.updated_at = now
        append_question_event(
            db,
            question_id=item.id,
            family_id=item.family_id,
            actor=actor,
            event_type="claimed",
            payload={"claim_token": claim_token, "agent_id": agent_id, "channel": channel, "expires_at": expires_at.isoformat()},
        )
        _publish_question_event(
            question=item,
            actor=actor,
            event_type="question.claimed",
            correlation_id=correlation_id,
            payload=_question_event_payload(
                item,
                extra_payload={
                    "claim_token": claim_token,
                    "delivery": {
                        "delivery_agent": agent_id,
                        "delivery_channel": channel,
                        "expires_at": expires_at.isoformat(),
                    },
                },
            ),
        )
    db.flush()
    return {"items": [question_response(item) for item in chosen], "claim_token": claim_token, "eligible": True, "reason": None}


def mark_question_asked(
    db: Session,
    *,
    question: QuestionRecord,
    actor: str,
    delivery_agent: str,
    delivery_channel: str,
    claim_token: str | None = None,
    delivery_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if claim_token and question.current_claim_token and claim_token != question.current_claim_token:
        raise HTTPException(status_code=409, detail="question claim token mismatch")
    before_state = _question_state(question)
    now = _utcnow()
    question.status = "asked"
    question.last_asked_at = now
    question.updated_at = now
    question.asked_count = int(question.asked_count or 0) + 1
    question.last_delivery_agent = delivery_agent
    question.last_delivery_channel = delivery_channel
    question.current_claim_token = None
    question.current_claim_agent = None
    question.current_claim_channel = None
    question.current_claimed_at = None
    question.current_claim_expires_at = None
    attempt = QuestionDeliveryAttempt(
        question_id=question.id,
        family_id=question.family_id,
        claim_token=claim_token,
        agent_id=delivery_agent,
        channel=delivery_channel,
        sent_at=now,
        outcome="sent",
        payload_json=delivery_context or {},
    )
    db.add(attempt)
    db.flush()
    event = append_question_event(
        db,
        question_id=question.id,
        family_id=question.family_id,
        actor=actor,
        event_type="asked",
        payload={"delivery_agent": delivery_agent, "delivery_channel": delivery_channel, "claim_token": claim_token},
    )
    _publish_question_event(
        question=question,
        actor=actor,
        event_type="question.asked",
        correlation_id=new_correlation_id(),
        payload=_question_event_payload(
            question,
            changed_fields=diff_field_paths(before_state, _question_state(question)),
            attempt=attempt,
            extra_payload={"event_id": event.id},
        ),
    )
    return {"question": question_response(question), "event": event_response(event), "attempt": attempt_response(attempt)}


def answer_question(
    db: Session,
    *,
    question: QuestionRecord,
    actor: str,
    answer_text: str,
    status: str,
    answer_sufficiency_state: str | None = None,
    resolution_note: str | None = None,
    responded_at: datetime | None = None,
    outcome: str = "responded",
    context_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before_state = _question_state(question)
    now = _sanitize_due_date(responded_at) or _utcnow()
    question.answer_text = answer_text.strip()
    question.answered_at = now
    question.status = status
    if answer_sufficiency_state is not None:
        question.answer_sufficiency_state = answer_sufficiency_state
    if context_patch:
        context = _question_context(question)
        context.update(context_patch)
        question.context_json = context
    question.updated_at = now
    question.current_claim_token = None
    question.current_claim_agent = None
    question.current_claim_channel = None
    question.current_claimed_at = None
    question.current_claim_expires_at = None

    attempt = db.execute(
        select(QuestionDeliveryAttempt)
        .where(
            QuestionDeliveryAttempt.question_id == question.id,
            QuestionDeliveryAttempt.responded_at.is_(None),
        )
        .order_by(QuestionDeliveryAttempt.sent_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if attempt is not None:
        attempt.responded_at = now
        attempt.outcome = outcome
        payload = dict(attempt.payload_json or {})
        if resolution_note:
            payload["resolution_note"] = resolution_note
        attempt.payload_json = payload
        db.flush()

    event = append_question_event(
        db,
        question_id=question.id,
        family_id=question.family_id,
        actor=actor,
        event_type="answered",
        payload={"status": status, "resolution_note": resolution_note or "", "answer_sufficiency_state": question.answer_sufficiency_state},
    )
    _publish_question_event(
        question=question,
        actor=actor,
        event_type="question.answered",
        correlation_id=new_correlation_id(),
        payload=_question_event_payload(
            question,
            changed_fields=diff_field_paths(before_state, _question_state(question)),
            resolution_note=resolution_note,
            attempt=attempt,
            extra_payload={"event_id": event.id, "response_outcome": outcome},
        ),
        occurred_at=now,
    )
    return {"question": question_response(question), "event": event_response(event), "attempt": attempt_response(attempt) if attempt else None}


def resolve_question(
    db: Session,
    *,
    question: QuestionRecord,
    actor: str,
    status: str,
    resolution_note: str | None = None,
    answer_sufficiency_state: str | None = None,
    context_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before_state = _question_state(question)
    now = _utcnow()
    question.status = status
    if answer_sufficiency_state is not None:
        question.answer_sufficiency_state = answer_sufficiency_state
    if context_patch:
        context = _question_context(question)
        context.update(context_patch)
        question.context_json = context
    question.updated_at = now
    question.current_claim_token = None
    question.current_claim_agent = None
    question.current_claim_channel = None
    question.current_claimed_at = None
    question.current_claim_expires_at = None
    if status == "resolved" and question.answered_at is None:
        question.answered_at = now
    db.flush()
    event = append_question_event(
        db,
        question_id=question.id,
        family_id=question.family_id,
        actor=actor,
        event_type=status,
        payload={"resolution_note": resolution_note or "", "answer_sufficiency_state": question.answer_sufficiency_state},
    )
    canonical_event_type = {
        "resolved": "question.resolved",
        "dismissed": "question.dismissed",
        "expired": "question.expired",
    }.get(status, "question.updated")
    _publish_question_event(
        question=question,
        actor=actor,
        event_type=canonical_event_type,
        correlation_id=new_correlation_id(),
        payload=_question_event_payload(
            question,
            changed_fields=diff_field_paths(before_state, _question_state(question)),
            resolution_note=resolution_note,
            extra_payload={"event_id": event.id},
        ),
        occurred_at=now,
    )
    return {"question": question_response(question), "event": event_response(event)}


def list_question_history(db: Session, *, family_id: int, question_id: str | None = None) -> dict[str, Any]:
    event_query = select(QuestionEvent).where(QuestionEvent.family_id == family_id)
    attempt_query = select(QuestionDeliveryAttempt).where(QuestionDeliveryAttempt.family_id == family_id)
    if question_id:
        event_query = event_query.where(QuestionEvent.question_id == question_id)
        attempt_query = attempt_query.where(QuestionDeliveryAttempt.question_id == question_id)
    events = db.execute(event_query.order_by(QuestionEvent.created_at.desc())).scalars().all()
    attempts = db.execute(attempt_query.order_by(QuestionDeliveryAttempt.sent_at.desc())).scalars().all()
    return {
        "events": [event_response(item) for item in events],
        "attempts": [attempt_response(item) for item in attempts],
    }


def delete_question(db: Session, *, question: QuestionRecord, actor: str) -> None:
    payload = _question_event_payload(question)
    correlation_id = new_correlation_id()
    db.delete(question)
    db.flush()
    _publish_question_event(
        question=question,
        actor=actor,
        event_type="question.deleted",
        correlation_id=correlation_id,
        payload=payload,
    )


def purge_questions(
    db: Session,
    *,
    family_id: int,
    actor: str,
    question_ids: list[str] | None = None,
    domain: str | None = None,
    status: str | None = None,
    category: str | None = None,
    purge_all: bool = False,
) -> int:
    if not purge_all and not question_ids and not any([domain, status, category]):
        raise HTTPException(status_code=400, detail="purge requires all=true or one or more filters")
    select_query = select(QuestionRecord).where(QuestionRecord.family_id == family_id)
    if question_ids:
        select_query = select_query.where(QuestionRecord.id.in_(question_ids))
    if domain:
        select_query = select_query.where(QuestionRecord.domain == domain)
    if status:
        select_query = select_query.where(QuestionRecord.status == status)
    if category:
        select_query = select_query.where(QuestionRecord.category == _normalize_category(category, None))
    items = db.execute(select_query).scalars().all()
    if not items:
        return 0
    result = db.execute(delete(QuestionRecord).where(QuestionRecord.id.in_([item.id for item in items])))
    db.flush()
    correlation_id = new_correlation_id()
    _publish_question_summary_event(
        family_id=family_id,
        actor=actor,
        event_type="question.purged",
        subject_id=f"purge:{family_id}:{correlation_id}",
        correlation_id=correlation_id,
        payload={
            "title": "Question backlog purge",
            "purged_count": len(items),
            "affected_question_ids": [item.id for item in items[:25]],
            "affected_domains": sorted({item.domain for item in items}),
            "affected_statuses": sorted({item.status for item in items}),
            "affected_source_agents": sorted({item.source_agent for item in items}),
            "filters": {
                "question_ids": question_ids or [],
                "domain": domain,
                "status": status,
                "category": _normalize_category(category, None) if category else None,
                "all": purge_all,
            },
        },
    )
    return int(result.rowcount or 0)


def refresh_engagement_windows(db: Session, *, timezone_name: str | None = None) -> dict[str, int]:
    zone = timezone_name or settings.question_default_timezone
    rows = db.execute(select(QuestionDeliveryAttempt)).scalars().all()
    buckets: dict[tuple[int, str, str, int], dict[str, float]] = defaultdict(lambda: {"attempts": 0.0, "responses": 0.0})
    for row in rows:
        bucket_hour = _safe_local_hour(row.responded_at or row.sent_at, zone)
        key = (row.family_id, row.agent_id, row.channel, bucket_hour)
        buckets[key]["attempts"] += 1.0
        if row.responded_at is not None or row.outcome == "responded":
            buckets[key]["responses"] += 1.0

    existing = {
        (item.family_id, item.agent_id, item.channel, item.local_hour): item
        for item in db.execute(select(QuestionEngagementWindow)).scalars().all()
    }
    touched = 0
    for key, stats in buckets.items():
        family_id, agent_id, channel, local_hour = key
        attempts = int(stats["attempts"])
        responses = int(stats["responses"])
        response_rate = (responses / attempts) if attempts else 0.0
        score = round((response_rate * 0.85) + (min(responses, 5) * 0.03) + (min(attempts, 8) * 0.01), 4)
        row = existing.get(key)
        if row is None:
            row = QuestionEngagementWindow(
                family_id=family_id,
                agent_id=agent_id,
                channel=channel,
                local_hour=local_hour,
            )
            db.add(row)
        row.attempt_count = attempts
        row.response_count = responses
        row.response_rate = response_rate
        row.score = score
        row.updated_at = _utcnow()
        touched += 1

    db.flush()
    return {"windows": touched, "attempts": len(rows)}
