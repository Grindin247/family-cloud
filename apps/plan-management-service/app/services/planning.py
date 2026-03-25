from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Iterable
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from agents.common.family_events import (
    build_event,
    diff_field_paths,
    make_privacy,
    new_correlation_id,
    publish_event as publish_family_event,
    snippet_fields,
)
from app.core.errors import raise_api_error
from app.models.planning import Plan, PlanCheckIn, PlanGoalLink, PlanInstance, PlanParticipant, PlanTaskSuggestion
from app.schemas.planning import (
    GoalOptionResponse,
    PlanAdherenceSummary,
    PlanAlignmentSummary,
    PlanCheckInCreate,
    PlanCheckInResponse,
    PlanCreate,
    PlanGoalLinkInput,
    PlanGoalLinkResponse,
    PlanInstanceResponse,
    PlanMilestone,
    PlanPreviewResponse,
    PlanResponse,
    PlanSchedule,
    PlanUpdate,
    TaskSuggestionInput,
    TaskSuggestionResponse,
)
from app.services import profile_api, question_api
from app.services.decision_api import get_goal

logger = logging.getLogger("family_cloud.plan_service")

WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass
class PlanContext:
    actor_id: str
    actor_type: str
    actor_person_id: str | None
    actor_email: str | None
    internal_admin: bool


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_actor(actor_email: str | None, *, internal_admin: bool) -> tuple[str, str]:
    if actor_email:
        return "user", actor_email.strip().lower()
    if internal_admin:
        return "system", "internal-admin"
    raise ValueError("missing actor identity")


def _zoneinfo(name: str | None) -> ZoneInfo:
    candidate = (name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(candidate)
    except Exception as exc:
        raise_api_error(422, "invalid_timezone", f"unknown timezone '{candidate}'", {"timezone": candidate, "error": str(exc)})
    raise AssertionError("unreachable")


def _plan_or_404(db: Session, *, family_id: int, plan_id: UUID) -> Plan:
    row = db.get(Plan, plan_id)
    if row is None or row.family_id != family_id:
        raise_api_error(404, "plan_not_found", "plan not found", {"family_id": family_id, "plan_id": str(plan_id)})
    return row


def _instance_or_404(db: Session, *, family_id: int, plan_id: UUID, instance_id: UUID) -> PlanInstance:
    row = db.get(PlanInstance, instance_id)
    if row is None or row.family_id != family_id or row.plan_id != plan_id:
        raise_api_error(
            404,
            "plan_instance_not_found",
            "plan instance not found",
            {"family_id": family_id, "plan_id": str(plan_id), "instance_id": str(instance_id)},
        )
    return row


def _list_participants(db: Session, *, plan_id: UUID) -> list[PlanParticipant]:
    return db.execute(select(PlanParticipant).where(PlanParticipant.plan_id == plan_id).order_by(PlanParticipant.person_id.asc())).scalars().all()


def _list_goal_links(db: Session, *, plan_id: UUID) -> list[PlanGoalLink]:
    return db.execute(select(PlanGoalLink).where(PlanGoalLink.plan_id == plan_id).order_by(PlanGoalLink.created_at.asc())).scalars().all()


def _list_task_suggestions(db: Session, *, plan_id: UUID) -> list[PlanTaskSuggestion]:
    return db.execute(select(PlanTaskSuggestion).where(PlanTaskSuggestion.plan_id == plan_id).order_by(PlanTaskSuggestion.created_at.asc())).scalars().all()


def _list_instances(db: Session, *, plan_id: UUID) -> list[PlanInstance]:
    return db.execute(select(PlanInstance).where(PlanInstance.plan_id == plan_id).order_by(PlanInstance.scheduled_for.asc())).scalars().all()


def _list_checkins(db: Session, *, plan_id: UUID) -> list[PlanCheckIn]:
    return db.execute(select(PlanCheckIn).where(PlanCheckIn.plan_id == plan_id).order_by(PlanCheckIn.created_at.asc())).scalars().all()


def _schedule_from_row(row: Plan) -> PlanSchedule:
    return PlanSchedule.model_validate(dict(row.schedule_json or {}))


def _milestones_from_row(row: Plan) -> list[PlanMilestone]:
    return [PlanMilestone.model_validate(item) for item in (row.milestones_json or [])]


def _participant_ids(db: Session, *, plan_id: UUID) -> list[str]:
    return [str(item.person_id) for item in _list_participants(db, plan_id=plan_id)]


def _goal_link_responses(db: Session, *, plan_id: UUID) -> list[PlanGoalLinkResponse]:
    return [
        PlanGoalLinkResponse(
            goal_id=item.goal_id,
            goal_scope=item.goal_scope,
            weight=item.weight,
            rationale=item.rationale,
            goal_name_snapshot=item.goal_name_snapshot,
        )
        for item in _list_goal_links(db, plan_id=plan_id)
    ]


def _task_suggestion_responses(db: Session, *, plan_id: UUID) -> list[TaskSuggestionResponse]:
    return [
        TaskSuggestionResponse(
            suggestion_id=str(item.suggestion_id),
            title=item.title,
            summary=item.summary,
            suggested_for=item.suggested_for,
            status=item.status,
            external_task_ref=item.external_task_ref,
        )
        for item in _list_task_suggestions(db, plan_id=plan_id)
    ]


def _instance_responses(db: Session, *, plan_id: UUID) -> list[PlanInstanceResponse]:
    return [
        PlanInstanceResponse(
            instance_id=str(item.instance_id),
            plan_id=str(item.plan_id),
            scheduled_for=_as_utc(item.scheduled_for),
            status=item.status,
            replacement_summary=item.replacement_summary,
            created_at=_as_utc(item.created_at),
            updated_at=_as_utc(item.updated_at),
        )
        for item in _list_instances(db, plan_id=plan_id)
    ]


def _checkin_response(row: PlanCheckIn) -> PlanCheckInResponse:
    return PlanCheckInResponse(
        checkin_id=str(row.checkin_id),
        plan_instance_id=str(row.plan_instance_id),
        status=row.status,
        note=row.note,
        rating=row.rating,
        blockers=list(row.blockers_json or []),
        confidence=row.confidence,
        qualitative_update=row.qualitative_update,
        created_by=row.created_by,
        created_at=_as_utc(row.created_at),
    )


def missing_fields_for_activation(row: Plan, participant_ids: Iterable[str]) -> list[str]:
    schedule = _schedule_from_row(row)
    missing: list[str] = []
    if row.owner_scope == "person" and row.owner_person_id is None:
        missing.append("owner_person_id")
    if not schedule.frequency:
        missing.append("schedule.frequency")
    if not schedule.timezone:
        missing.append("schedule.timezone")
    if schedule.frequency == "weekly" and not schedule.weekdays:
        missing.append("schedule.weekdays")
    if row.owner_scope == "family" and not list(participant_ids):
        missing.append("participant_person_ids")
    return missing


def _alignment_summary(goal_links: list[PlanGoalLinkResponse]) -> PlanAlignmentSummary:
    total_weight = round(sum(item.weight for item in goal_links), 2)
    if total_weight <= 0:
        label = "unlinked"
    elif total_weight < 0.75:
        label = "light"
    elif total_weight < 1.5:
        label = "moderate"
    else:
        label = "strong"
    if goal_links:
        summary = f"Supports {len(goal_links)} linked goal(s)."
    else:
        summary = "No goals linked yet."
    return PlanAlignmentSummary(
        label=label,
        linked_goal_count=len(goal_links),
        total_weight=total_weight,
        goals=goal_links,
        summary=summary,
    )


def _adherence_summary(instances: list[PlanInstanceResponse]) -> PlanAdherenceSummary:
    cutoff = utcnow() - timedelta(days=30)
    recent = [item for item in instances if item.scheduled_for >= cutoff]
    completed = sum(1 for item in recent if item.status == "done")
    skipped = sum(1 for item in recent if item.status == "skipped")
    missed = sum(1 for item in recent if item.status == "missed")
    denominator = completed + skipped + missed
    adherence_rate = round(completed / denominator, 2) if denominator else 0.0
    if denominator == 0:
        label = "new"
    elif adherence_rate >= 0.75:
        label = "strong"
    elif adherence_rate >= 0.5:
        label = "steady"
    else:
        label = "watch"
    upcoming = sum(1 for item in instances if item.status == "scheduled" and item.scheduled_for >= utcnow())
    return PlanAdherenceSummary(
        label=label,
        completed_count=completed,
        skipped_count=skipped,
        missed_count=missed,
        adherence_rate=adherence_rate,
        upcoming_count=upcoming,
    )


def _profile_signals(*, family_id: int, person_ids: list[str], actor_email: str | None, internal_admin: bool) -> list[str]:
    signals: list[str] = []
    for person_id in person_ids:
        detail = profile_api.get_profile_detail(
            family_id=family_id,
            person_id=person_id,
            actor_email=actor_email,
            internal_admin=internal_admin,
        )
        if not detail:
            continue
        preferences = detail.get("preferences") if isinstance(detail, dict) else {}
        if not isinstance(preferences, dict):
            continue
        dietary = preferences.get("dietary_preferences") if isinstance(preferences.get("dietary_preferences"), dict) else {}
        accessibility = preferences.get("accessibility_needs") if isinstance(preferences.get("accessibility_needs"), dict) else {}
        learning = preferences.get("learning_preferences") if isinstance(preferences.get("learning_preferences"), dict) else {}
        motivation = preferences.get("motivation_style") if isinstance(preferences.get("motivation_style"), dict) else {}
        communication = preferences.get("communication_preferences") if isinstance(preferences.get("communication_preferences"), dict) else {}
        if dietary and (dietary.get("allergies") or dietary.get("restrictions")):
            signals.append(f"{person_id}: dietary constraints present")
        if accessibility and (accessibility.get("accommodations") or accessibility.get("notes")):
            signals.append(f"{person_id}: accessibility support noted")
        if learning and (learning.get("modalities") or learning.get("notes")):
            signals.append(f"{person_id}: learning preferences available")
        if motivation and (motivation.get("encouragements") or motivation.get("notes")):
            signals.append(f"{person_id}: motivation style available")
        if communication and (communication.get("preferred_channels") or communication.get("notes")):
            signals.append(f"{person_id}: communication preferences available")
    return signals


def _merge_feasibility_summary(
    *,
    base: dict[str, Any],
    profile_signals: list[str],
    missing_fields: list[str],
) -> dict[str, Any]:
    summary = dict(base or {})
    if profile_signals:
        summary["profile_signals"] = profile_signals
    if missing_fields:
        summary["missing_fields"] = missing_fields
    if "status" not in summary:
        summary["status"] = "draft" if missing_fields else "ready"
    return summary


def _validate_person_ids(*, persons_by_id: dict[str, dict[str, Any]], person_ids: Iterable[str]) -> None:
    for person_id in person_ids:
        if person_id not in persons_by_id:
            raise_api_error(404, "person_not_found", "person not found for family", {"person_id": person_id})


def _validated_goal_links(
    *,
    family_id: int,
    goal_links: list[PlanGoalLinkInput],
    actor_email: str | None,
    internal_admin: bool,
) -> list[GoalOptionResponse]:
    validated: list[GoalOptionResponse] = []
    for item in goal_links:
        goal = get_goal(goal_id=item.goal_id, actor_email=actor_email, internal_admin=internal_admin)
        if int(goal.get("family_id", 0)) != family_id:
            raise_api_error(422, "goal_family_mismatch", "goal does not belong to this family", {"goal_id": item.goal_id, "family_id": family_id})
        validated.append(
            GoalOptionResponse(
                goal_id=item.goal_id,
                name=str(item.goal_name_snapshot or goal.get("name") or f"Goal {item.goal_id}"),
                scope_type=str(goal.get("scope_type") or item.goal_scope),
                owner_person_id=str(goal.get("owner_person_id")) if goal.get("owner_person_id") else None,
                status=str(goal.get("status") or "active"),
                weight=float(goal.get("weight")) if goal.get("weight") is not None else None,
                description=goal.get("description"),
            )
        )
    return validated


def _replace_participants(db: Session, *, plan_id: UUID, family_id: int, participant_person_ids: list[str]) -> None:
    db.execute(delete(PlanParticipant).where(PlanParticipant.plan_id == plan_id))
    for person_id in participant_person_ids:
        db.add(PlanParticipant(plan_id=plan_id, family_id=family_id, person_id=UUID(person_id), created_at=utcnow()))


def _replace_goal_links(
    db: Session,
    *,
    plan_id: UUID,
    family_id: int,
    goal_links: list[PlanGoalLinkInput],
    validated_goals: list[GoalOptionResponse],
) -> None:
    db.execute(delete(PlanGoalLink).where(PlanGoalLink.plan_id == plan_id))
    goal_map = {item.goal_id: item for item in validated_goals}
    for item in goal_links:
        goal = goal_map[item.goal_id]
        db.add(
            PlanGoalLink(
                plan_id=plan_id,
                family_id=family_id,
                goal_id=item.goal_id,
                goal_scope=item.goal_scope,
                weight=item.weight,
                rationale=item.rationale,
                goal_name_snapshot=goal.name,
                created_at=utcnow(),
            )
        )


def _replace_task_suggestions(db: Session, *, plan_id: UUID, family_id: int, task_suggestions: list[TaskSuggestionInput]) -> None:
    db.execute(delete(PlanTaskSuggestion).where(PlanTaskSuggestion.plan_id == plan_id))
    now = utcnow()
    for item in task_suggestions:
        db.add(
            PlanTaskSuggestion(
                plan_id=plan_id,
                family_id=family_id,
                title=item.title,
                summary=item.summary,
                suggested_for=item.suggested_for,
                status=item.status,
                external_task_ref=item.external_task_ref,
                created_at=now,
                updated_at=now,
            )
        )


def _datetime_for_occurrence(*, occurrence_date: date, timezone_name: str | None, local_time_value: time | None) -> datetime:
    tz = _zoneinfo(timezone_name)
    local_dt = datetime.combine(occurrence_date, local_time_value or time(hour=0, minute=0), tzinfo=tz)
    return local_dt.astimezone(UTC)


def _occurrences_for_window(row: Plan, *, days: int = 14) -> list[datetime]:
    schedule = _schedule_from_row(row)
    if not schedule.frequency:
        return []
    anchor_date = row.start_date or row.created_at.date()
    start = max(anchor_date, utcnow().date())
    end = start + timedelta(days=max(days, 1) - 1)
    excluded = {item for item in schedule.excluded_dates}
    items: list[datetime] = []
    cursor = start
    while cursor <= end:
        if cursor > (row.end_date or cursor):
            break
        if cursor in excluded:
            cursor += timedelta(days=1)
            continue
        include = False
        if schedule.frequency == "daily":
            include = ((cursor - anchor_date).days % schedule.interval) == 0 if cursor >= anchor_date else False
        elif schedule.frequency == "weekly":
            weekdays = {WEEKDAY_INDEX[item] for item in schedule.weekdays}
            if cursor >= anchor_date and cursor.weekday() in weekdays:
                include = (((cursor - anchor_date).days // 7) % schedule.interval) == 0
        if include:
            items.append(_datetime_for_occurrence(occurrence_date=cursor, timezone_name=schedule.timezone, local_time_value=schedule.local_time))
        cursor += timedelta(days=1)
    return items


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()


def _schedule_summary(row: Plan) -> dict[str, Any]:
    schedule = _schedule_from_row(row)
    return {
        "frequency": schedule.frequency,
        "interval": schedule.interval,
        "timezone": schedule.timezone,
        "weekdays": list(schedule.weekdays or []),
        "local_time": schedule.local_time.isoformat() if schedule.local_time else None,
        "excluded_dates": [item.isoformat() for item in schedule.excluded_dates],
    }


def _plan_state(db: Session, *, row: Plan) -> dict[str, Any]:
    participants = _participant_ids(db, plan_id=row.plan_id)
    goal_links = _goal_link_responses(db, plan_id=row.plan_id)
    task_suggestions = _task_suggestion_responses(db, plan_id=row.plan_id)
    instances = _instance_responses(db, plan_id=row.plan_id)
    milestones = _milestones_from_row(row)
    return {
        "title": row.title,
        "summary": row.summary,
        "plan_kind": row.plan_kind,
        "status": row.status,
        "owner_scope": row.owner_scope,
        "owner_person_id": str(row.owner_person_id) if row.owner_person_id else None,
        "participant_person_ids": participants,
        "schedule": _schedule_summary(row),
        "start_date": row.start_date.isoformat() if row.start_date else None,
        "end_date": row.end_date.isoformat() if row.end_date else None,
        "milestones": [item.model_dump(mode="json") for item in milestones],
        "goal_links": [item.model_dump(mode="json") for item in goal_links],
        "task_suggestions": [item.model_dump(mode="json") for item in task_suggestions],
        "feasibility_summary": dict(row.feasibility_summary_json or {}),
        "adherence_summary": _adherence_summary(instances).model_dump(mode="json"),
        "missing_fields": missing_fields_for_activation(row, participants),
    }


def _plan_event_payload(
    db: Session,
    *,
    row: Plan,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    participants = _participant_ids(db, plan_id=row.plan_id)
    goal_links = _goal_link_responses(db, plan_id=row.plan_id)
    task_suggestions = _task_suggestion_responses(db, plan_id=row.plan_id)
    instances = _instance_responses(db, plan_id=row.plan_id)
    milestones = _milestones_from_row(row)
    adherence = _adherence_summary(instances).model_dump(mode="json")
    payload: dict[str, Any] = {
        "plan_id": str(row.plan_id),
        "status": row.status,
        "plan_kind": row.plan_kind,
        "owner_scope": row.owner_scope,
        "owner_person_id": str(row.owner_person_id) if row.owner_person_id else None,
        "participant_person_ids": participants,
        "participant_count": len(participants),
        "goal_ids": [item.goal_id for item in goal_links],
        "goal_count": len(goal_links),
        "milestone_count": len(milestones),
        "task_suggestion_count": len(task_suggestions),
        "schedule_summary": _schedule_summary(row),
        "adherence_summary": adherence,
        "checkin_count": len(_list_checkins(db, plan_id=row.plan_id)),
        "missing_fields": missing_fields_for_activation(row, participants),
        "feasibility_status": str((row.feasibility_summary_json or {}).get("status") or ""),
        "start_date": row.start_date.isoformat() if row.start_date else None,
        "end_date": row.end_date.isoformat() if row.end_date else None,
        "created_at": _isoformat(row.created_at),
        "updated_at": _isoformat(row.updated_at),
        "archived_at": _isoformat(row.archived_at),
    }
    if extra_payload:
        payload.update({key: value for key, value in extra_payload.items() if value is not None})
    payload.update(snippet_fields("title", row.title))
    payload.update(snippet_fields("summary", row.summary))
    payload["title"] = payload.get("title_snippet") or f"Plan {row.plan_id}"
    return payload


def _publish_plan_event(
    *,
    db: Session,
    row: Plan,
    event_type: str,
    actor_id: str,
    actor_type: str,
    actor_person_id: str | None,
    payload: dict[str, Any] | None,
    tags: list[str],
    correlation_id: str | None = None,
) -> None:
    try:
        full_payload = _plan_event_payload(db, row=row, extra_payload=payload)
        event = build_event(
            family_id=row.family_id,
            domain="planning",
            event_type=event_type,
            actor={"actor_type": actor_type, "actor_id": actor_id, "person_id": actor_person_id},
            subject={"subject_type": "plan", "subject_id": str(row.plan_id), "person_id": str(row.owner_person_id) if row.owner_person_id else None},
            payload=full_payload,
            source={"agent_id": "PlanningService", "runtime": "backend"},
            privacy=make_privacy(
                contains_pii=True,
                contains_child_data=bool(row.owner_person_id),
                contains_free_text=any(key.endswith("_snippet") for key in full_payload),
            ),
            tags=tags,
            correlation_id=correlation_id,
        )
        publish_family_event(event)
    except Exception:
        logger.exception("Failed to publish planning event family_id=%s event_type=%s plan_id=%s", row.family_id, event_type, row.plan_id)


def reconcile_plan_instances(db: Session, *, row: Plan, context: PlanContext) -> list[PlanInstance]:
    if row.status != "active":
        return _list_instances(db, plan_id=row.plan_id)

    now = utcnow()
    instances = _list_instances(db, plan_id=row.plan_id)
    changed = False
    for instance in instances:
        if instance.status == "scheduled" and _as_utc(instance.scheduled_for) < now:
            instance.status = "missed"
            instance.updated_at = now
            changed = True
            db.flush()
            _publish_plan_event(
                db=db,
                row=row,
                event_type="plan.instance.missed",
                actor_id=context.actor_id,
                actor_type=context.actor_type,
                actor_person_id=context.actor_person_id,
                payload={"plan_id": str(row.plan_id), "instance_id": str(instance.instance_id), "scheduled_for": instance.scheduled_for.isoformat()},
                tags=["planning", row.plan_kind, "instance"],
            )

    existing_by_time = {_as_utc(item.scheduled_for): item for item in instances}
    for scheduled_for in _occurrences_for_window(row, days=14):
        if scheduled_for in existing_by_time:
            continue
        instance = PlanInstance(
            instance_id=uuid.uuid4(),
            plan_id=row.plan_id,
            family_id=row.family_id,
            scheduled_for=scheduled_for,
            status="scheduled",
            created_at=now,
            updated_at=now,
        )
        db.add(instance)
        changed = True
        db.flush()
        _publish_plan_event(
            db=db,
            row=row,
            event_type="plan.instance.scheduled",
            actor_id=context.actor_id,
            actor_type=context.actor_type,
            actor_person_id=context.actor_person_id,
            payload={"plan_id": str(row.plan_id), "instance_id": str(instance.instance_id), "scheduled_for": scheduled_for.isoformat()},
            tags=["planning", row.plan_kind, "instance"],
        )
    if changed:
        row.updated_at = now
        db.commit()
    return _list_instances(db, plan_id=row.plan_id)


def build_plan_response(db: Session, *, row: Plan) -> PlanResponse:
    participants = _participant_ids(db, plan_id=row.plan_id)
    goal_links = _goal_link_responses(db, plan_id=row.plan_id)
    task_suggestions = _task_suggestion_responses(db, plan_id=row.plan_id)
    instances = _instance_responses(db, plan_id=row.plan_id)
    missing_fields = missing_fields_for_activation(row, participants)
    return PlanResponse(
        plan_id=str(row.plan_id),
        family_id=row.family_id,
        title=row.title,
        summary=row.summary,
        plan_kind=row.plan_kind,
        status=row.status,
        owner_scope=row.owner_scope,
        owner_person_id=str(row.owner_person_id) if row.owner_person_id else None,
        participant_person_ids=participants,
        schedule=_schedule_from_row(row),
        start_date=row.start_date,
        end_date=row.end_date,
        milestones=_milestones_from_row(row),
        goal_links=goal_links,
        task_suggestions=task_suggestions,
        alignment_summary=_alignment_summary(goal_links),
        feasibility_summary=dict(row.feasibility_summary_json or {}),
        adherence_summary=_adherence_summary(instances),
        missing_fields=missing_fields,
        created_at=row.created_at,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
    )


def list_plans(
    db: Session,
    *,
    family_id: int,
    status: str | None = None,
    owner_scope: str | None = None,
    owner_person_id: str | None = None,
    plan_kind: str | None = None,
) -> list[Plan]:
    query = select(Plan).where(Plan.family_id == family_id)
    if status:
        query = query.where(Plan.status == status)
    if owner_scope:
        query = query.where(Plan.owner_scope == owner_scope)
    if owner_person_id:
        query = query.where(Plan.owner_person_id == UUID(owner_person_id))
    if plan_kind:
        query = query.where(Plan.plan_kind == plan_kind)
    return db.execute(query.order_by(Plan.updated_at.desc(), Plan.created_at.desc())).scalars().all()


def create_plan(
    db: Session,
    *,
    family_id: int,
    payload: PlanCreate,
    context: PlanContext,
    persons_by_id: dict[str, dict[str, Any]],
) -> Plan:
    participant_person_ids = payload.participant_person_ids
    _validate_person_ids(persons_by_id=persons_by_id, person_ids=participant_person_ids)
    if payload.owner_person_id and payload.owner_person_id not in persons_by_id:
        raise_api_error(404, "person_not_found", "person not found for family", {"person_id": payload.owner_person_id})

    validated_goals = _validated_goal_links(
        family_id=family_id,
        goal_links=payload.goal_links,
        actor_email=context.actor_email,
        internal_admin=context.internal_admin,
    )
    now = utcnow()
    row = Plan(
        family_id=family_id,
        title=payload.title,
        summary=payload.summary,
        plan_kind=payload.plan_kind,
        status=payload.status,
        owner_scope=payload.owner_scope,
        owner_person_id=UUID(payload.owner_person_id) if payload.owner_person_id else None,
        schedule_json=payload.schedule.model_dump(mode="json"),
        start_date=payload.start_date,
        end_date=payload.end_date,
        milestones_json=[item.model_dump(mode="json") for item in payload.milestones],
        feasibility_summary_json={},
        created_by=context.actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()

    _replace_participants(db, plan_id=row.plan_id, family_id=family_id, participant_person_ids=participant_person_ids)
    _replace_goal_links(db, plan_id=row.plan_id, family_id=family_id, goal_links=payload.goal_links, validated_goals=validated_goals)
    _replace_task_suggestions(db, plan_id=row.plan_id, family_id=family_id, task_suggestions=payload.task_suggestions)

    missing_fields = missing_fields_for_activation(row, participant_person_ids)
    if row.status == "active" and missing_fields:
        raise_api_error(422, "plan_activation_blocked", "plan is missing required activation fields", {"missing_fields": missing_fields})
    row.feasibility_summary_json = _merge_feasibility_summary(
        base=payload.feasibility_summary,
        profile_signals=_profile_signals(
            family_id=family_id,
            person_ids=[*participant_person_ids, *([payload.owner_person_id] if payload.owner_person_id else [])],
            actor_email=context.actor_email,
            internal_admin=context.internal_admin,
        ),
        missing_fields=missing_fields,
    )
    db.commit()
    db.refresh(row)
    _publish_plan_event(
        db=db,
        row=row,
        event_type="plan.created",
        actor_id=context.actor_id,
        actor_type=context.actor_type,
        actor_person_id=context.actor_person_id,
        payload={"plan_id": str(row.plan_id), "title": row.title, "status": row.status, "plan_kind": row.plan_kind},
        tags=["planning", row.plan_kind],
    )
    if row.status == "active":
        reconcile_plan_instances(db, row=row, context=context)
    queue_missing_field_questions(row=row, missing_fields=missing_fields, context=context)
    return _plan_or_404(db, family_id=family_id, plan_id=row.plan_id)


def update_plan(
    db: Session,
    *,
    row: Plan,
    payload: PlanUpdate,
    context: PlanContext,
    persons_by_id: dict[str, dict[str, Any]],
) -> Plan:
    before_state = _plan_state(db, row=row)
    next_owner_scope = payload.owner_scope or row.owner_scope
    next_owner_person_id = payload.owner_person_id if payload.owner_person_id is not None else (str(row.owner_person_id) if row.owner_person_id else None)
    next_participants = payload.participant_person_ids if payload.participant_person_ids is not None else _participant_ids(db, plan_id=row.plan_id)
    next_goal_links = payload.goal_links if payload.goal_links is not None else [
        PlanGoalLinkInput(
            goal_id=item.goal_id,
            goal_scope=item.goal_scope,
            weight=item.weight,
            rationale=item.rationale,
            goal_name_snapshot=item.goal_name_snapshot,
        )
        for item in _goal_link_responses(db, plan_id=row.plan_id)
    ]
    validated_goals = _validated_goal_links(
        family_id=row.family_id,
        goal_links=next_goal_links,
        actor_email=context.actor_email,
        internal_admin=context.internal_admin,
    )

    _validate_person_ids(persons_by_id=persons_by_id, person_ids=next_participants)
    if next_owner_person_id and next_owner_person_id not in persons_by_id:
        raise_api_error(404, "person_not_found", "person not found for family", {"person_id": next_owner_person_id})

    if payload.title is not None:
        row.title = payload.title
    if payload.summary is not None:
        row.summary = payload.summary
    if payload.plan_kind is not None:
        row.plan_kind = payload.plan_kind
    if payload.status is not None:
        row.status = payload.status
    row.owner_scope = next_owner_scope
    row.owner_person_id = UUID(next_owner_person_id) if next_owner_person_id else None
    if payload.schedule is not None:
        row.schedule_json = payload.schedule.model_dump(mode="json")
    if payload.start_date is not None:
        row.start_date = payload.start_date
    if payload.end_date is not None:
        row.end_date = payload.end_date
    if payload.milestones is not None:
        row.milestones_json = [item.model_dump(mode="json") for item in payload.milestones]

    _replace_participants(db, plan_id=row.plan_id, family_id=row.family_id, participant_person_ids=next_participants)
    _replace_goal_links(db, plan_id=row.plan_id, family_id=row.family_id, goal_links=next_goal_links, validated_goals=validated_goals)
    if payload.task_suggestions is not None:
        _replace_task_suggestions(db, plan_id=row.plan_id, family_id=row.family_id, task_suggestions=payload.task_suggestions)

    missing_fields = missing_fields_for_activation(row, next_participants)
    if row.status == "active" and missing_fields:
        raise_api_error(422, "plan_activation_blocked", "plan is missing required activation fields", {"missing_fields": missing_fields})
    row.feasibility_summary_json = _merge_feasibility_summary(
        base=payload.feasibility_summary if payload.feasibility_summary is not None else dict(row.feasibility_summary_json or {}),
        profile_signals=_profile_signals(
            family_id=row.family_id,
            person_ids=[*next_participants, *([next_owner_person_id] if next_owner_person_id else [])],
            actor_email=context.actor_email,
            internal_admin=context.internal_admin,
        ),
        missing_fields=missing_fields,
    )
    row.updated_at = utcnow()
    if row.status == "archived":
        row.archived_at = row.updated_at
    db.commit()
    db.refresh(row)
    after_state = _plan_state(db, row=row)
    changed_fields = diff_field_paths(before_state, after_state)
    correlation_id = new_correlation_id()
    _publish_plan_event(
        db=db,
        row=row,
        event_type="plan.updated",
        actor_id=context.actor_id,
        actor_type=context.actor_type,
        actor_person_id=context.actor_person_id,
        payload={
            "plan_id": str(row.plan_id),
            "title": row.title,
            "status": row.status,
            "plan_kind": row.plan_kind,
            "changed_fields": changed_fields,
        },
        tags=["planning", row.plan_kind],
        correlation_id=correlation_id,
    )
    if any(item.goal_id for item in next_goal_links):
        _publish_plan_event(
            db=db,
            row=row,
            event_type="plan.goal_linked",
            actor_id=context.actor_id,
            actor_type=context.actor_type,
            actor_person_id=context.actor_person_id,
            payload={"plan_id": str(row.plan_id), "goal_ids": [item.goal_id for item in next_goal_links]},
            tags=["planning", row.plan_kind, "goal-link"],
            correlation_id=correlation_id,
        )
    if row.status == "active":
        reconcile_plan_instances(db, row=row, context=context)
    queue_missing_field_questions(row=row, missing_fields=missing_fields, context=context)
    return _plan_or_404(db, family_id=row.family_id, plan_id=row.plan_id)


def activate_plan(db: Session, *, row: Plan, context: PlanContext) -> Plan:
    participant_ids = _participant_ids(db, plan_id=row.plan_id)
    missing_fields = missing_fields_for_activation(row, participant_ids)
    if missing_fields:
        raise_api_error(422, "plan_activation_blocked", "plan is missing required activation fields", {"missing_fields": missing_fields})
    row.status = "active"
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    _publish_plan_event(
        db=db,
        row=row,
        event_type="plan.activated",
        actor_id=context.actor_id,
        actor_type=context.actor_type,
        actor_person_id=context.actor_person_id,
        payload={"plan_id": str(row.plan_id), "status": row.status},
        tags=["planning", row.plan_kind],
    )
    reconcile_plan_instances(db, row=row, context=context)
    return _plan_or_404(db, family_id=row.family_id, plan_id=row.plan_id)


def pause_plan(db: Session, *, row: Plan, context: PlanContext) -> Plan:
    row.status = "paused"
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    _publish_plan_event(
        db=db,
        row=row,
        event_type="plan.paused",
        actor_id=context.actor_id,
        actor_type=context.actor_type,
        actor_person_id=context.actor_person_id,
        payload={"plan_id": str(row.plan_id), "status": row.status},
        tags=["planning", row.plan_kind],
    )
    return row


def archive_plan(db: Session, *, row: Plan, context: PlanContext) -> Plan:
    row.status = "archived"
    row.archived_at = utcnow()
    row.updated_at = row.archived_at
    db.commit()
    db.refresh(row)
    _publish_plan_event(
        db=db,
        row=row,
        event_type="plan.archived",
        actor_id=context.actor_id,
        actor_type=context.actor_type,
        actor_person_id=context.actor_person_id,
        payload={"plan_id": str(row.plan_id), "status": row.status},
        tags=["planning", row.plan_kind],
    )
    return row


def preview_plan(db: Session, *, row: Plan, days: int) -> PlanPreviewResponse:
    preview_items = [
        PlanInstanceResponse(
            instance_id=f"preview-{index}",
            plan_id=str(row.plan_id),
            scheduled_for=scheduled_for,
            status="scheduled",
            replacement_summary=None,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for index, scheduled_for in enumerate(_occurrences_for_window(row, days=days), start=1)
    ]
    participant_ids = _participant_ids(db, plan_id=row.plan_id)
    return PlanPreviewResponse(
        plan_id=str(row.plan_id),
        days=days,
        items=preview_items,
        task_suggestions=_task_suggestion_responses(db, plan_id=row.plan_id),
        missing_fields=missing_fields_for_activation(row, participant_ids),
    )


def list_goal_options(*, goals: list[dict[str, Any]]) -> list[GoalOptionResponse]:
    return [
        GoalOptionResponse(
            goal_id=int(item["id"]),
            name=str(item.get("name") or item["id"]),
            scope_type=str(item.get("scope_type") or "family"),
            owner_person_id=str(item.get("owner_person_id")) if item.get("owner_person_id") else None,
            status=str(item.get("status") or "active"),
            weight=float(item["weight"]) if item.get("weight") is not None else None,
            description=item.get("description"),
        )
        for item in goals
        if item.get("id") is not None
    ]


def record_checkin(
    db: Session,
    *,
    row: Plan,
    payload: PlanCheckInCreate,
    context: PlanContext,
) -> PlanCheckInResponse:
    instance = _instance_or_404(db, family_id=row.family_id, plan_id=row.plan_id, instance_id=UUID(payload.plan_instance_id))
    instance.status = payload.status
    instance.updated_at = utcnow()
    checkin = PlanCheckIn(
        plan_id=row.plan_id,
        plan_instance_id=instance.instance_id,
        family_id=row.family_id,
        status=payload.status,
        note=payload.note,
        rating=payload.rating,
        blockers_json=payload.blockers,
        confidence=payload.confidence,
        qualitative_update=payload.qualitative_update,
        created_by=context.actor_id,
        created_at=utcnow(),
    )
    db.add(checkin)
    db.commit()
    db.refresh(checkin)
    correlation_id = new_correlation_id()

    event_type = {
        "done": "plan.instance.completed",
        "skipped": "plan.instance.skipped",
        "missed": "plan.instance.missed",
        "scheduled": "plan.instance.scheduled",
    }.get(payload.status, "plan.instance.completed")
    _publish_plan_event(
        db=db,
        row=row,
        event_type=event_type,
        actor_id=context.actor_id,
        actor_type=context.actor_type,
        actor_person_id=context.actor_person_id,
        payload={
            "plan_id": str(row.plan_id),
            "instance_id": str(instance.instance_id),
            "status": payload.status,
            "scheduled_for": instance.scheduled_for.isoformat(),
            "changed_fields": ["status", "updated_at"],
        },
        tags=["planning", row.plan_kind, "instance"],
        correlation_id=correlation_id,
    )
    _publish_plan_event(
        db=db,
        row=row,
        event_type="plan.checkin.recorded",
        actor_id=context.actor_id,
        actor_type=context.actor_type,
        actor_person_id=context.actor_person_id,
        payload={
            "plan_id": str(row.plan_id),
            "instance_id": str(instance.instance_id),
            "checkin_id": str(checkin.checkin_id),
            "status": payload.status,
            "rating": payload.rating,
            "confidence": payload.confidence,
            "blocker_count": len(payload.blockers or []),
            **snippet_fields("checkin_note", payload.note),
            **snippet_fields("checkin_blockers", " | ".join(payload.blockers or [])),
            **snippet_fields("qualitative_update", payload.qualitative_update),
        },
        tags=["planning", row.plan_kind, "checkin"],
        correlation_id=correlation_id,
    )
    return _checkin_response(checkin)


def queue_missing_field_questions(*, row: Plan, missing_fields: list[str], context: PlanContext) -> None:
    if row.status != "draft" or not missing_fields:
        return
    for field_name in missing_fields:
        prompt = {
            "owner_person_id": "Who should own this individual plan?",
            "schedule.frequency": "Should this plan repeat daily or weekly?",
            "schedule.timezone": "Which timezone should this plan use for scheduling?",
            "schedule.weekdays": "Which weekdays should this weekly plan run on?",
            "participant_person_ids": "Who should participate in this family plan?",
        }.get(field_name, f"What should we fill in for {field_name}?")
        question_api.create_question(
            family_id=row.family_id,
            actor_email=context.actor_email,
            internal_admin=context.internal_admin,
            payload={
                "domain": "planning",
                "source_agent": "planning-agent",
                "topic": f"Missing planning field: {field_name}",
                "summary": f"Plan '{row.title}' is still missing {field_name}.",
                "prompt": prompt,
                "urgency": "medium",
                "category": "plan_missing_field",
                "topic_type": "plan_missing_field",
                "dedupe_key": f"plan:{row.plan_id}:{field_name}",
                "context": {
                    "plan_id": str(row.plan_id),
                    "plan_kind": row.plan_kind,
                    "field_name": field_name,
                },
                "artifact_refs": [{"type": "plan", "id": str(row.plan_id)}],
            },
        )
