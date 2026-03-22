from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.common.family_events import build_event, make_privacy, publish_event as publish_family_event
from app.core.config import settings
from app.core.errors import raise_api_error
from app.models.education import (
    Assessment,
    Assignment,
    Domain,
    EventLog,
    IdempotencyKey,
    JournalEntry,
    LearnerProfile,
    LearningActivity,
    LearningGoal,
    PracticeRepetition,
    ProgressSnapshot,
    QuizItem,
    QuizResponse,
    QuizSession,
    Skill,
)

DEFAULT_DOMAINS: list[dict[str, str]] = [
    {"code": "math", "name": "Math", "description": "Mathematics and numeracy"},
    {"code": "reading", "name": "Reading", "description": "Reading and comprehension"},
    {"code": "writing", "name": "Writing", "description": "Writing and composition"},
    {"code": "music", "name": "Music", "description": "Music, performance, and theory"},
    {"code": "home-economics", "name": "Home Economics", "description": "Home economics and daily living"},
    {"code": "science", "name": "Science", "description": "Science and inquiry"},
    {"code": "social-studies", "name": "Social Studies", "description": "History, civics, and society"},
    {"code": "life-skills", "name": "Life Skills", "description": "Life skills and independence"},
    {"code": "coding", "name": "Coding", "description": "Programming and computational thinking"},
]


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_actor(actor_email: str | None, *, internal_admin: bool) -> tuple[str, str | None]:
    if actor_email:
        return "user", actor_email.strip().lower()
    if internal_admin:
        return "system", "internal-admin"
    raise_api_error(401, "missing_auth", "missing auth header (X-Forwarded-User or X-Dev-User)")
    raise AssertionError("unreachable")


def route_request_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(jsonable_encoder(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def scope_key(domain_id: UUID | None, skill_id: UUID | None) -> str:
    if domain_id is None and skill_id is None:
        return "all"
    return f"{domain_id or 'none'}:{skill_id or 'none'}"


def percent_value(*, score: float | None, max_score: float | None, percent: float | None) -> float | None:
    if percent is not None:
        return percent
    if score is None or max_score in (None, 0):
        return None
    return (score / max_score) * 100.0


def ensure_seed_data(db: Session) -> None:
    exists = db.execute(select(Domain.domain_id).limit(1)).first()
    if exists is not None:
        return
    for row in DEFAULT_DOMAINS:
        db.add(Domain(code=row["code"], name=row["name"], description=row["description"]))
    db.commit()


def consume_idempotency(
    db: Session,
    *,
    family_id: int,
    route_key: str,
    idempotency_key: str | None,
    payload: Any,
) -> dict[str, Any] | None:
    if not idempotency_key:
        return None
    request_hash = route_request_hash(payload)
    row = db.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.family_id == family_id,
            IdempotencyKey.route_key == route_key,
            IdempotencyKey.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.request_hash != request_hash:
        raise_api_error(
            409,
            "idempotency_conflict",
            "idempotency key already used for a different request payload",
            {"route_key": route_key, "idempotency_key": idempotency_key},
        )
    return row.response_json


def store_idempotency_result(
    db: Session,
    *,
    family_id: int,
    route_key: str,
    idempotency_key: str | None,
    payload: Any,
    response_json: dict[str, Any],
    status_code: int,
    resource_type: str | None,
    resource_id: str | None,
) -> None:
    if not idempotency_key:
        return
    now = utcnow()
    row = IdempotencyKey(
        family_id=family_id,
        route_key=route_key,
        idempotency_key=idempotency_key,
        request_hash=route_request_hash(payload),
        response_json=response_json,
        status_code=status_code,
        resource_type=resource_type,
        resource_id=resource_id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)


def filter_scope(items: list[Any], *, domain_id: UUID | None, skill_id: UUID | None, occurred_attr: str | None = None) -> list[Any]:
    filtered: list[Any] = []
    for item in items:
        if domain_id is not None and getattr(item, "domain_id", None) != domain_id:
            continue
        if skill_id is not None and getattr(item, "skill_id", None) != skill_id:
            continue
        if occurred_attr is not None and getattr(item, occurred_attr, None) is None:
            continue
        filtered.append(item)
    return filtered


def calculate_stats(
    db: Session,
    *,
    family_id: int,
    learner_id: UUID,
    domain_id: UUID | None = None,
    skill_id: UUID | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    as_of_date = as_of or utcnow().date()
    now_boundary = datetime.combine(as_of_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    start_7 = now_boundary - timedelta(days=7)
    start_30 = now_boundary - timedelta(days=30)

    activities = filter_scope(
        db.execute(
            select(LearningActivity).where(
                LearningActivity.family_id == family_id,
                LearningActivity.learner_id == learner_id,
            )
        ).scalars().all(),
        domain_id=domain_id,
        skill_id=skill_id,
    )
    practices = filter_scope(
        db.execute(
            select(PracticeRepetition).where(
                PracticeRepetition.family_id == family_id,
                PracticeRepetition.learner_id == learner_id,
            )
        ).scalars().all(),
        domain_id=domain_id,
        skill_id=skill_id,
    )
    assessments = filter_scope(
        db.execute(
            select(Assessment).where(
                Assessment.family_id == family_id,
                Assessment.learner_id == learner_id,
            )
        ).scalars().all(),
        domain_id=domain_id,
        skill_id=skill_id,
    )
    assignments = filter_scope(
        db.execute(
            select(Assignment).where(
                Assignment.family_id == family_id,
                Assignment.learner_id == learner_id,
            )
        ).scalars().all(),
        domain_id=domain_id,
        skill_id=skill_id,
    )
    journals = db.execute(
        select(JournalEntry).where(
            JournalEntry.family_id == family_id,
            JournalEntry.learner_id == learner_id,
        )
    ).scalars().all()
    quiz_sessions = filter_scope(
        db.execute(
            select(QuizSession).where(
                QuizSession.family_id == family_id,
                QuizSession.learner_id == learner_id,
            )
        ).scalars().all(),
        domain_id=domain_id,
        skill_id=skill_id,
    )

    activities_7 = [item for item in activities if (occurred_at := as_utc(item.occurred_at)) is not None and start_7 <= occurred_at < now_boundary]
    activities_30 = [item for item in activities if (occurred_at := as_utc(item.occurred_at)) is not None and start_30 <= occurred_at < now_boundary]
    practices_7 = [item for item in practices if (occurred_at := as_utc(item.occurred_at)) is not None and start_7 <= occurred_at < now_boundary]
    practices_30 = [item for item in practices if (occurred_at := as_utc(item.occurred_at)) is not None and start_30 <= occurred_at < now_boundary]
    assessments_30 = [item for item in assessments if (occurred_at := as_utc(item.occurred_at)) is not None and start_30 <= occurred_at < now_boundary]
    journals_30 = [item for item in journals if (occurred_at := as_utc(item.occurred_at)) is not None and start_30 <= occurred_at < now_boundary]
    quizzes_30 = [item for item in quiz_sessions if (created_at := as_utc(item.created_at)) is not None and start_30 <= created_at < now_boundary]

    assessment_scores = [
        percent_value(score=item.score, max_score=item.max_score, percent=item.percent)
        for item in assessments_30
    ]
    normalized_scores = [item for item in assessment_scores if item is not None]
    latest_assessment = next(iter(sorted(assessments, key=lambda item: as_utc(item.occurred_at) or datetime.min.replace(tzinfo=UTC), reverse=True)), None)
    latest_practice = next(iter(sorted(practices, key=lambda item: as_utc(item.occurred_at) or datetime.min.replace(tzinfo=UTC), reverse=True)), None)

    total_seconds = sum(item.duration_seconds or 0 for item in activities_30)
    total_seconds += sum(item.duration_seconds or 0 for item in practices_30)

    return {
        "family_id": family_id,
        "learner_id": learner_id,
        "domain_id": domain_id,
        "skill_id": skill_id,
        "as_of_date": as_of_date,
        "activity_count_7d": len(activities_7),
        "activity_count_30d": len(activities_30),
        "practice_count_7d": len(practices_7),
        "practice_count_30d": len(practices_30),
        "assessment_count_30d": len(assessments_30),
        "avg_score_30d": round(sum(normalized_scores) / len(normalized_scores), 2) if normalized_scores else None,
        "latest_score": percent_value(
            score=latest_assessment.score if latest_assessment is not None else None,
            max_score=latest_assessment.max_score if latest_assessment is not None else None,
            percent=latest_assessment.percent if latest_assessment is not None else None,
        )
        if latest_assessment is not None
        else None,
        "latest_assessment_at": as_utc(latest_assessment.occurred_at) if latest_assessment is not None else None,
        "total_minutes_30d": round(total_seconds / 60.0, 2) if total_seconds else None,
        "assignment_open_count": len([item for item in assignments if item.status not in {"completed", "done"}]),
        "assignment_completed_count": len([item for item in assignments if item.status in {"completed", "done"}]),
        "journal_count_30d": len(journals_30),
        "quiz_session_count_30d": len(quizzes_30),
        "days_since_last_practice": (as_of_date - as_utc(latest_practice.occurred_at).date()).days if latest_practice is not None and as_utc(latest_practice.occurred_at) is not None else None,
    }


def upsert_snapshot(
    db: Session,
    *,
    family_id: int,
    learner_id: UUID,
    domain_id: UUID | None,
    skill_id: UUID | None,
    as_of: date | None = None,
) -> ProgressSnapshot:
    stats = calculate_stats(db, family_id=family_id, learner_id=learner_id, domain_id=domain_id, skill_id=skill_id, as_of=as_of)
    row = db.execute(
        select(ProgressSnapshot).where(
            ProgressSnapshot.family_id == family_id,
            ProgressSnapshot.learner_id == learner_id,
            ProgressSnapshot.scope_key == scope_key(domain_id, skill_id),
            ProgressSnapshot.as_of_date == stats["as_of_date"],
        )
    ).scalar_one_or_none()
    now = utcnow()
    if row is None:
        row = ProgressSnapshot(
            family_id=family_id,
            learner_id=learner_id,
            domain_id=domain_id,
            skill_id=skill_id,
            scope_key=scope_key(domain_id, skill_id),
            as_of_date=stats["as_of_date"],
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    row.activity_count_7d = stats["activity_count_7d"]
    row.activity_count_30d = stats["activity_count_30d"]
    row.practice_count_7d = stats["practice_count_7d"]
    row.practice_count_30d = stats["practice_count_30d"]
    row.assessment_count_30d = stats["assessment_count_30d"]
    row.avg_score_30d = stats["avg_score_30d"]
    row.latest_score = stats["latest_score"]
    row.latest_assessment_at = stats["latest_assessment_at"]
    row.total_minutes_30d = stats["total_minutes_30d"]
    row.updated_at = now
    db.flush()
    return row


def refresh_snapshots(
    db: Session,
    *,
    family_id: int,
    learner_id: UUID,
    domain_id: UUID | None,
    skill_id: UUID | None,
) -> list[ProgressSnapshot]:
    rows = [upsert_snapshot(db, family_id=family_id, learner_id=learner_id, domain_id=None, skill_id=None)]
    if domain_id is not None or skill_id is not None:
        rows.append(upsert_snapshot(db, family_id=family_id, learner_id=learner_id, domain_id=domain_id, skill_id=skill_id))
    return rows


def refresh_snapshot_scopes(
    db: Session,
    *,
    family_id: int,
    learner_id: UUID,
    scopes: set[tuple[UUID | None, UUID | None]],
) -> list[ProgressSnapshot]:
    rows: list[ProgressSnapshot] = []
    normalized_scopes = {(None, None), *scopes}
    for domain_id, skill_id in normalized_scopes:
        rows.append(upsert_snapshot(db, family_id=family_id, learner_id=learner_id, domain_id=domain_id, skill_id=skill_id))
    return rows


def refresh_snapshot_transition(
    db: Session,
    *,
    family_id: int,
    learner_id: UUID,
    previous_domain_id: UUID | None,
    previous_skill_id: UUID | None,
    next_domain_id: UUID | None,
    next_skill_id: UUID | None,
) -> list[ProgressSnapshot]:
    return refresh_snapshot_scopes(
        db,
        family_id=family_id,
        learner_id=learner_id,
        scopes={
            (previous_domain_id, previous_skill_id),
            (next_domain_id, next_skill_id),
        },
    )


def assignment_is_open(status: str | None) -> bool:
    return str(status or "").strip().lower() not in {"completed", "done"}


def _assignment_focus_key(item: Assignment) -> tuple[int, datetime]:
    due_at = as_utc(item.due_at)
    assigned_at = as_utc(item.assigned_at)
    created_at = as_utc(item.created_at)
    if due_at is not None:
        return (0, due_at)
    if assigned_at is not None:
        return (1, assigned_at)
    if created_at is not None:
        return (2, created_at)
    return (3, datetime.max.replace(tzinfo=UTC))


def dashboard_score_trend(
    db: Session,
    *,
    family_id: int,
    learner_id: UUID,
    limit: int = 8,
) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(ProgressSnapshot)
            .where(
                ProgressSnapshot.family_id == family_id,
                ProgressSnapshot.learner_id == learner_id,
                ProgressSnapshot.scope_key == "all",
            )
            .order_by(ProgressSnapshot.as_of_date.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    rows.reverse()
    return [
        {
            "as_of_date": row.as_of_date,
            "value": row.avg_score_30d if row.avg_score_30d is not None else row.latest_score,
        }
        for row in rows
    ]


def build_family_dashboard(
    db: Session,
    *,
    family_id: int,
    family_persons: list[dict[str, Any]],
) -> dict[str, Any]:
    learners = (
        db.execute(select(LearnerProfile).where(LearnerProfile.family_id == family_id).order_by(LearnerProfile.display_name.asc()))
        .scalars()
        .all()
    )

    tracked_person_ids = {str(learner.learner_id) for learner in learners}
    tracked_rows: list[dict[str, Any]] = []
    total_active_goals = 0
    total_open_assignments = 0
    score_values: list[float] = []
    total_minutes_values: list[float] = []

    for learner in learners:
        active_goals = (
            db.execute(
                select(LearningGoal)
                .where(
                    LearningGoal.family_id == family_id,
                    LearningGoal.learner_id == learner.learner_id,
                    LearningGoal.status == "active",
                )
                .order_by(LearningGoal.created_at.desc())
            )
            .scalars()
            .all()
        )
        assignments = (
            db.execute(
                select(Assignment)
                .where(
                    Assignment.family_id == family_id,
                    Assignment.learner_id == learner.learner_id,
                )
            )
            .scalars()
            .all()
        )
        open_assignments = sorted((item for item in assignments if assignment_is_open(item.status)), key=_assignment_focus_key)
        latest_activity = (
            db.execute(
                select(LearningActivity)
                .where(
                    LearningActivity.family_id == family_id,
                    LearningActivity.learner_id == learner.learner_id,
                )
                .order_by(LearningActivity.occurred_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        stats = calculate_stats(db, family_id=family_id, learner_id=learner.learner_id)

        current_focus_text = None
        if open_assignments:
            current_focus_text = open_assignments[0].title
        elif active_goals:
            current_focus_text = active_goals[0].title
        elif latest_activity is not None:
            current_focus_text = latest_activity.title

        total_active_goals += len(active_goals)
        total_open_assignments += len(open_assignments)
        if stats["avg_score_30d"] is not None:
            score_values.append(float(stats["avg_score_30d"]))
        if stats["total_minutes_30d"] is not None:
            total_minutes_values.append(float(stats["total_minutes_30d"]))

        tracked_rows.append(
            {
                "learner": learner,
                "current_focus_text": current_focus_text,
                "last_activity_at": as_utc(latest_activity.occurred_at) if latest_activity is not None else None,
                "active_goal_count": len(active_goals),
                "open_assignment_count": len(open_assignments),
                "avg_score_30d": stats["avg_score_30d"],
                "latest_score": stats["latest_score"],
                "total_minutes_30d": stats["total_minutes_30d"],
                "days_since_last_practice": stats["days_since_last_practice"],
                "score_trend_points": dashboard_score_trend(db, family_id=family_id, learner_id=learner.learner_id),
            }
        )

    untracked_persons = [
        {
            "person_id": str(person.get("person_id") or ""),
            "display_name": str(person.get("display_name") or person.get("canonical_name") or person.get("person_id") or "Unknown"),
            "role_in_family": person.get("role_in_family"),
            "is_admin": bool(person.get("is_admin")),
            "status": str(person.get("status") or "active"),
        }
        for person in family_persons
        if str(person.get("status") or "active") == "active" and str(person.get("person_id") or "") not in tracked_person_ids
    ]

    return {
        "family_id": family_id,
        "kpis": {
            "tracked_learner_count": len(tracked_rows),
            "untracked_person_count": len(untracked_persons),
            "active_goal_count": total_active_goals,
            "open_assignment_count": total_open_assignments,
            "avg_score_30d": round(sum(score_values) / len(score_values), 2) if score_values else None,
            "total_minutes_30d": round(sum(total_minutes_values), 2) if total_minutes_values else None,
        },
        "tracked_learners": tracked_rows,
        "untracked_persons": untracked_persons,
    }


def create_event_log(
    db: Session,
    *,
    family_id: int,
    actor_type: str,
    actor_id: str | None,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    contains_free_text: bool = False,
) -> EventLog:
    event = build_event(
        family_id=family_id,
        domain="education",
        event_type=event_type,
        actor={"actor_type": actor_type, "actor_id": actor_id or "unknown"},
        subject={"subject_type": "education", "subject_id": entity_id},
        payload={**payload, "entity_type": entity_type, "entity_id": entity_id},
        source={"agent_id": "EducationService", "runtime": "backend"},
        privacy=make_privacy(
            classification="family",
            contains_pii=True,
            contains_child_data=True,
            contains_free_text=contains_free_text,
        ),
        integrity={"producer": "EducationService", "idempotency_key": idempotency_key},
    )
    row = EventLog(
        family_id=family_id,
        occurred_at=utcnow(),
        actor_type=actor_type,
        actor_id=actor_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        idempotency_key=idempotency_key,
        payload_json=jsonable_encoder(payload),
        canonical_event_json=event,
        publish_status="pending",
        publish_attempts=0,
    )
    db.add(row)
    db.flush()
    return row


def try_publish_event_rows(db: Session, *, event_ids: list[str] | None = None, limit: int | None = None) -> dict[str, Any]:
    query = select(EventLog).where(EventLog.publish_status.in_(("pending", "failed"))).order_by(EventLog.created_at.asc())
    if event_ids:
        normalized_ids = [UUID(str(item)) for item in event_ids]
        query = query.where(EventLog.event_id.in_(normalized_ids))
    if limit is not None:
        query = query.limit(limit)
    rows = db.execute(query).scalars().all()
    published = 0
    failed = 0
    for row in rows:
        try:
            publish_family_event(row.canonical_event_json)
            row.publish_status = "published"
            row.publish_attempts += 1
            row.last_publish_error = None
            row.published_at = utcnow()
            published += 1
        except Exception as exc:
            row.publish_status = "failed"
            row.publish_attempts += 1
            row.last_publish_error = str(exc)
            failed += 1
    db.commit()
    return {"published": published, "failed": failed, "scanned": len(rows)}


def update_quiz_totals(db: Session, *, quiz_id: UUID) -> None:
    session = db.get(QuizSession, quiz_id)
    if session is None:
        return
    items = db.execute(select(QuizItem).where(QuizItem.quiz_id == quiz_id)).scalars().all()
    responses = db.execute(select(QuizResponse).where(QuizResponse.quiz_id == quiz_id)).scalars().all()
    session.total_items = len(items)
    session.total_score = round(sum(item.score or 0.0 for item in responses), 2) if responses else None
    session.max_score = round(sum(item.max_score or 0.0 for item in items), 2) if items else None


def recent_rows(db: Session, model, *, family_id: int, learner_id: UUID, limit: int, order_attr: str = "created_at") -> list[Any]:
    order_column = getattr(model, order_attr)
    return (
        db.execute(
            select(model).where(model.family_id == family_id, model.learner_id == learner_id).order_by(order_column.desc()).limit(limit)
        )
        .scalars()
        .all()
    )
