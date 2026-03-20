from __future__ import annotations

from datetime import UTC
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import raise_api_error
from app.models.education import (
    Assessment,
    Assignment,
    Attachment,
    Domain,
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
from app.schemas.education import (
    ActivityCreate,
    ActivityResponse,
    AssessmentCreate,
    AssessmentResponse,
    AssignmentCreate,
    AssignmentResponse,
    AssignmentUpdate,
    AttachmentCreate,
    AttachmentResponse,
    DomainResponse,
    EducationSummaryResponse,
    GoalCreate,
    GoalResponse,
    GoalUpdate,
    JournalCreate,
    JournalResponse,
    LearnerCreate,
    LearnerResponse,
    PracticeRepetitionCreate,
    PracticeRepetitionResponse,
    ProgressSnapshotResponse,
    QuizCreate,
    QuizDetailResponse,
    QuizItemResponse,
    QuizItemsCreate,
    QuizResponseRecord,
    QuizResponsesCreate,
    QuizSessionResponse,
    SkillResponse,
    StatsResponse,
)
from app.services.decision_api import ensure_education_enabled, ensure_family_access, get_family_person
from app.services.education import (
    calculate_stats,
    consume_idempotency,
    create_event_log,
    ensure_seed_data,
    normalize_actor,
    recent_rows,
    refresh_snapshots,
    store_idempotency_result,
    try_publish_event_rows,
    update_quiz_totals,
    utcnow,
)

router = APIRouter(prefix="/v1", tags=["education"])


def _is_internal_admin(x_internal_admin_token: str | None) -> bool:
    return bool(x_internal_admin_token and x_internal_admin_token == settings.internal_admin_token)


def _caller_email(x_forwarded_user: str | None, x_dev_user: str | None) -> str | None:
    for candidate in (x_forwarded_user, x_dev_user):
        if candidate and candidate.strip():
            return candidate.strip().lower()
    return None


def _ensure_scope(*, family_id: int, actor_email: str | None, internal_admin: bool) -> None:
    ensure_family_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    ensure_education_enabled(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)


def _learner_or_404(db: Session, *, family_id: int, learner_id: UUID) -> LearnerProfile:
    learner = db.get(LearnerProfile, learner_id)
    if learner is None or learner.family_id != family_id:
        raise_api_error(404, "learner_not_found", "learner not found", {"family_id": family_id, "learner_id": str(learner_id)})
    return learner


def _domain_or_404(db: Session, domain_id: UUID | None) -> Domain | None:
    if domain_id is None:
        return None
    row = db.get(Domain, domain_id)
    if row is None:
        raise_api_error(404, "domain_not_found", "domain not found", {"domain_id": str(domain_id)})
    return row


def _skill_or_404(db: Session, skill_id: UUID | None) -> Skill | None:
    if skill_id is None:
        return None
    row = db.get(Skill, skill_id)
    if row is None:
        raise_api_error(404, "skill_not_found", "skill not found", {"skill_id": str(skill_id)})
    return row


def _assignment_or_404(db: Session, assignment_id: UUID | None, *, family_id: int | None = None) -> Assignment | None:
    if assignment_id is None:
        return None
    row = db.get(Assignment, assignment_id)
    if row is None or (family_id is not None and row.family_id != family_id):
        raise_api_error(404, "assignment_not_found", "assignment not found", {"assignment_id": str(assignment_id)})
    return row


def _activity_or_404(db: Session, activity_id: UUID | None, *, family_id: int | None = None) -> LearningActivity | None:
    if activity_id is None:
        return None
    row = db.get(LearningActivity, activity_id)
    if row is None or (family_id is not None and row.family_id != family_id):
        raise_api_error(404, "activity_not_found", "activity not found", {"activity_id": str(activity_id)})
    return row


def _quiz_or_404(db: Session, *, family_id: int, quiz_id: UUID) -> QuizSession:
    row = db.get(QuizSession, quiz_id)
    if row is None or row.family_id != family_id:
        raise_api_error(404, "quiz_not_found", "quiz not found", {"quiz_id": str(quiz_id)})
    return row


def _goal_or_404(db: Session, *, goal_id: UUID) -> LearningGoal:
    row = db.get(LearningGoal, goal_id)
    if row is None:
        raise_api_error(404, "goal_not_found", "goal not found", {"goal_id": str(goal_id)})
    return row


def _serialize(model_cls, obj):
    return model_cls.model_validate(obj, from_attributes=True)


@router.get("/domains", response_model=list[DomainResponse])
def list_domains(
    family_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    ensure_seed_data(db)
    return [_serialize(DomainResponse, item) for item in db.execute(select(Domain).order_by(Domain.name.asc())).scalars().all()]


@router.get("/skills", response_model=list[SkillResponse])
def list_skills(
    family_id: int = Query(..., ge=1),
    domain_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    ensure_seed_data(db)
    query = select(Skill)
    if domain_id is not None:
        query = query.where(Skill.domain_id == domain_id)
    return [_serialize(SkillResponse, item) for item in db.execute(query.order_by(Skill.name.asc())).scalars().all()]


@router.get("/domains/{domain_id}/skills", response_model=list[SkillResponse])
def list_domain_skills(
    domain_id: UUID,
    family_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    _domain_or_404(db, domain_id)
    return [_serialize(SkillResponse, item) for item in db.execute(select(Skill).where(Skill.domain_id == domain_id).order_by(Skill.name.asc())).scalars().all()]


@router.post("/learners", response_model=LearnerResponse, status_code=201)
def create_learner(
    payload: LearnerCreate,
    db: Session = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=payload.family_id, actor_email=actor, internal_admin=internal_admin)
    cached = consume_idempotency(db, family_id=payload.family_id, route_key="POST:/v1/learners", idempotency_key=x_idempotency_key, payload=payload)
    if cached is not None:
        return cached

    person = get_family_person(
        family_id=payload.family_id,
        learner_id=str(payload.learner_id),
        actor_email=actor,
        internal_admin=internal_admin,
    )
    existing = db.get(LearnerProfile, payload.learner_id)
    if existing is not None:
        raise_api_error(409, "learner_exists", "learner profile already exists", {"learner_id": str(payload.learner_id)})

    now = utcnow()
    learner = LearnerProfile(
        learner_id=payload.learner_id,
        family_id=payload.family_id,
        display_name=payload.display_name or str(person.get("display_name") or person.get("canonical_name") or payload.learner_id),
        birthdate=payload.birthdate,
        timezone=payload.timezone,
        status=payload.status,
        created_at=now,
        updated_at=now,
    )
    db.add(learner)
    actor_type, actor_id = normalize_actor(actor, internal_admin=internal_admin)
    event = create_event_log(
        db,
        family_id=payload.family_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type="education.learner.created",
        entity_type="learner",
        entity_id=str(payload.learner_id),
        payload={"learner_id": str(payload.learner_id), "display_name": learner.display_name, "status": learner.status},
        idempotency_key=x_idempotency_key,
    )
    response = _serialize(LearnerResponse, learner)
    response_json = jsonable_encoder(response)
    store_idempotency_result(
        db,
        family_id=payload.family_id,
        route_key="POST:/v1/learners",
        idempotency_key=x_idempotency_key,
        payload=payload,
        response_json=response_json,
        status_code=201,
        resource_type="learner",
        resource_id=str(payload.learner_id),
    )
    db.commit()
    try_publish_event_rows(db, event_ids=[str(event.event_id)])
    return response_json


@router.get("/learners", response_model=list[LearnerResponse])
def list_learners(
    family_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    return [_serialize(LearnerResponse, item) for item in db.execute(select(LearnerProfile).where(LearnerProfile.family_id == family_id).order_by(LearnerProfile.display_name.asc())).scalars().all()]


@router.get("/learners/{learner_id}", response_model=LearnerResponse)
def get_learner(
    learner_id: UUID,
    family_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    return _serialize(LearnerResponse, _learner_or_404(db, family_id=family_id, learner_id=learner_id))


@router.post("/goals", response_model=GoalResponse, status_code=201)
def create_goal(
    payload: GoalCreate,
    db: Session = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=payload.family_id, actor_email=actor, internal_admin=internal_admin)
    ensure_seed_data(db)
    cached = consume_idempotency(db, family_id=payload.family_id, route_key="POST:/v1/goals", idempotency_key=x_idempotency_key, payload=payload)
    if cached is not None:
        return cached
    _learner_or_404(db, family_id=payload.family_id, learner_id=payload.learner_id)
    _domain_or_404(db, payload.domain_id)
    _skill_or_404(db, payload.skill_id)
    now = utcnow()
    row = LearningGoal(**payload.model_dump(), created_at=now, updated_at=now)
    db.add(row)
    db.flush()
    actor_type, actor_id = normalize_actor(actor, internal_admin=internal_admin)
    event = create_event_log(
        db,
        family_id=payload.family_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type="education.goal.created",
        entity_type="goal",
        entity_id=str(row.goal_id),
        payload={"goal_id": str(row.goal_id), "learner_id": str(row.learner_id), "title": row.title, "status": row.status},
        idempotency_key=x_idempotency_key,
    )
    response = _serialize(GoalResponse, row)
    response_json = jsonable_encoder(response)
    store_idempotency_result(
        db,
        family_id=payload.family_id,
        route_key="POST:/v1/goals",
        idempotency_key=x_idempotency_key,
        payload=payload,
        response_json=response_json,
        status_code=201,
        resource_type="goal",
        resource_id=str(row.goal_id),
    )
    db.commit()
    try_publish_event_rows(db, event_ids=[str(event.event_id)])
    return response_json


@router.patch("/goals/{goal_id}", response_model=GoalResponse)
def update_goal(
    goal_id: UUID,
    payload: GoalUpdate,
    db: Session = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    row = _goal_or_404(db, goal_id=goal_id)
    _ensure_scope(family_id=row.family_id, actor_email=actor, internal_admin=internal_admin)
    cached = consume_idempotency(db, family_id=row.family_id, route_key=f"PATCH:/v1/goals/{goal_id}", idempotency_key=x_idempotency_key, payload=payload)
    if cached is not None:
        return cached
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise_api_error(400, "empty_patch", "at least one field must be provided")
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_at = utcnow()
    actor_type, actor_id = normalize_actor(actor, internal_admin=internal_admin)
    event = create_event_log(
        db,
        family_id=row.family_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type="education.goal.updated",
        entity_type="goal",
        entity_id=str(row.goal_id),
        payload={"goal_id": str(row.goal_id), "learner_id": str(row.learner_id), "title": row.title, "status": row.status},
        idempotency_key=x_idempotency_key,
    )
    response = _serialize(GoalResponse, row)
    response_json = jsonable_encoder(response)
    store_idempotency_result(
        db,
        family_id=row.family_id,
        route_key=f"PATCH:/v1/goals/{goal_id}",
        idempotency_key=x_idempotency_key,
        payload=payload,
        response_json=response_json,
        status_code=200,
        resource_type="goal",
        resource_id=str(row.goal_id),
    )
    db.commit()
    try_publish_event_rows(db, event_ids=[str(event.event_id)])
    return response_json


@router.get("/learners/{learner_id}/goals", response_model=list[GoalResponse])
def list_goals(
    learner_id: UUID,
    family_id: int = Query(..., ge=1),
    active_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    _learner_or_404(db, family_id=family_id, learner_id=learner_id)
    query = select(LearningGoal).where(LearningGoal.family_id == family_id, LearningGoal.learner_id == learner_id)
    if active_only:
        query = query.where(LearningGoal.status == "active")
    return [_serialize(GoalResponse, item) for item in db.execute(query.order_by(LearningGoal.created_at.desc())).scalars().all()]


@router.post("/activities", response_model=ActivityResponse, status_code=201)
def create_activity(
    payload: ActivityCreate,
    db: Session = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=payload.family_id, actor_email=actor, internal_admin=internal_admin)
    ensure_seed_data(db)
    cached = consume_idempotency(db, family_id=payload.family_id, route_key="POST:/v1/activities", idempotency_key=x_idempotency_key, payload=payload)
    if cached is not None:
        return cached
    _learner_or_404(db, family_id=payload.family_id, learner_id=payload.learner_id)
    _domain_or_404(db, payload.domain_id)
    _skill_or_404(db, payload.skill_id)
    row = LearningActivity(
        **payload.model_dump(exclude={"created_by"}),
        created_by=payload.created_by or (actor or "system"),
        created_at=utcnow(),
    )
    db.add(row)
    db.flush()
    refresh_snapshots(db, family_id=row.family_id, learner_id=row.learner_id, domain_id=row.domain_id, skill_id=row.skill_id)
    actor_type, actor_id = normalize_actor(actor, internal_admin=internal_admin)
    event = create_event_log(
        db,
        family_id=row.family_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type="education.activity.recorded",
        entity_type="activity",
        entity_id=str(row.activity_id),
        payload={"activity_id": str(row.activity_id), "learner_id": str(row.learner_id), "activity_type": row.activity_type, "title": row.title},
        idempotency_key=x_idempotency_key,
    )
    response = _serialize(ActivityResponse, row)
    response_json = jsonable_encoder(response)
    store_idempotency_result(
        db,
        family_id=row.family_id,
        route_key="POST:/v1/activities",
        idempotency_key=x_idempotency_key,
        payload=payload,
        response_json=response_json,
        status_code=201,
        resource_type="activity",
        resource_id=str(row.activity_id),
    )
    db.commit()
    try_publish_event_rows(db, event_ids=[str(event.event_id)])
    return response_json


@router.get("/learners/{learner_id}/activities", response_model=list[ActivityResponse])
def list_activities(
    learner_id: UUID,
    family_id: int = Query(..., ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    _learner_or_404(db, family_id=family_id, learner_id=learner_id)
    return [_serialize(ActivityResponse, item) for item in recent_rows(db, LearningActivity, family_id=family_id, learner_id=learner_id, limit=limit, order_attr="occurred_at")]


@router.post("/assignments", response_model=AssignmentResponse, status_code=201)
def create_assignment(
    payload: AssignmentCreate,
    db: Session = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=payload.family_id, actor_email=actor, internal_admin=internal_admin)
    ensure_seed_data(db)
    cached = consume_idempotency(db, family_id=payload.family_id, route_key="POST:/v1/assignments", idempotency_key=x_idempotency_key, payload=payload)
    if cached is not None:
        return cached
    _learner_or_404(db, family_id=payload.family_id, learner_id=payload.learner_id)
    _domain_or_404(db, payload.domain_id)
    _skill_or_404(db, payload.skill_id)
    _activity_or_404(db, payload.activity_id, family_id=payload.family_id)
    now = utcnow()
    row = Assignment(**payload.model_dump(), created_at=now, updated_at=now)
    db.add(row)
    db.flush()
    actor_type, actor_id = normalize_actor(actor, internal_admin=internal_admin)
    event = create_event_log(
        db,
        family_id=row.family_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type="education.assignment.created",
        entity_type="assignment",
        entity_id=str(row.assignment_id),
        payload={"assignment_id": str(row.assignment_id), "learner_id": str(row.learner_id), "title": row.title, "status": row.status},
        idempotency_key=x_idempotency_key,
    )
    response = _serialize(AssignmentResponse, row)
    response_json = jsonable_encoder(response)
    store_idempotency_result(
        db,
        family_id=row.family_id,
        route_key="POST:/v1/assignments",
        idempotency_key=x_idempotency_key,
        payload=payload,
        response_json=response_json,
        status_code=201,
        resource_type="assignment",
        resource_id=str(row.assignment_id),
    )
    db.commit()
    try_publish_event_rows(db, event_ids=[str(event.event_id)])
    return response_json


@router.patch("/assignments/{assignment_id}", response_model=AssignmentResponse)
def update_assignment(
    assignment_id: UUID,
    payload: AssignmentUpdate,
    db: Session = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    row = _assignment_or_404(db, assignment_id, family_id=None)
    assert row is not None
    _ensure_scope(family_id=row.family_id, actor_email=actor, internal_admin=internal_admin)
    cached = consume_idempotency(db, family_id=row.family_id, route_key=f"PATCH:/v1/assignments/{assignment_id}", idempotency_key=x_idempotency_key, payload=payload)
    if cached is not None:
        return cached
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise_api_error(400, "empty_patch", "at least one field must be provided")
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_at = utcnow()
    actor_type, actor_id = normalize_actor(actor, internal_admin=internal_admin)
    event = create_event_log(
        db,
        family_id=row.family_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type="education.assignment.updated",
        entity_type="assignment",
        entity_id=str(row.assignment_id),
        payload={"assignment_id": str(row.assignment_id), "learner_id": str(row.learner_id), "title": row.title, "status": row.status},
        idempotency_key=x_idempotency_key,
    )
    response = _serialize(AssignmentResponse, row)
    response_json = jsonable_encoder(response)
    store_idempotency_result(
        db,
        family_id=row.family_id,
        route_key=f"PATCH:/v1/assignments/{assignment_id}",
        idempotency_key=x_idempotency_key,
        payload=payload,
        response_json=response_json,
        status_code=200,
        resource_type="assignment",
        resource_id=str(row.assignment_id),
    )
    db.commit()
    try_publish_event_rows(db, event_ids=[str(event.event_id)])
    return response_json


@router.get("/learners/{learner_id}/assignments", response_model=list[AssignmentResponse])
def list_assignments(
    learner_id: UUID,
    family_id: int = Query(..., ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    _learner_or_404(db, family_id=family_id, learner_id=learner_id)
    return [_serialize(AssignmentResponse, item) for item in recent_rows(db, Assignment, family_id=family_id, learner_id=learner_id, limit=limit)]


@router.post("/assessments", response_model=AssessmentResponse, status_code=201)
def create_assessment(
    payload: AssessmentCreate,
    db: Session = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=payload.family_id, actor_email=actor, internal_admin=internal_admin)
    ensure_seed_data(db)
    cached = consume_idempotency(db, family_id=payload.family_id, route_key="POST:/v1/assessments", idempotency_key=x_idempotency_key, payload=payload)
    if cached is not None:
        return cached
    _learner_or_404(db, family_id=payload.family_id, learner_id=payload.learner_id)
    _domain_or_404(db, payload.domain_id)
    _skill_or_404(db, payload.skill_id)
    _assignment_or_404(db, payload.assignment_id, family_id=payload.family_id)
    _activity_or_404(db, payload.activity_id, family_id=payload.family_id)
    row = Assessment(
        **payload.model_dump(exclude={"graded_by"}),
        graded_by=payload.graded_by or (actor or "system"),
        created_at=utcnow(),
    )
    db.add(row)
    db.flush()
    refresh_snapshots(db, family_id=row.family_id, learner_id=row.learner_id, domain_id=row.domain_id, skill_id=row.skill_id)
    actor_type, actor_id = normalize_actor(actor, internal_admin=internal_admin)
    event = create_event_log(
        db,
        family_id=row.family_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type="education.assessment.recorded",
        entity_type="assessment",
        entity_id=str(row.assessment_id),
        payload={"assessment_id": str(row.assessment_id), "learner_id": str(row.learner_id), "title": row.title, "percent": row.percent, "score": row.score},
        idempotency_key=x_idempotency_key,
        contains_free_text=bool(row.notes),
    )
    response = _serialize(AssessmentResponse, row)
    response_json = jsonable_encoder(response)
    store_idempotency_result(
        db,
        family_id=row.family_id,
        route_key="POST:/v1/assessments",
        idempotency_key=x_idempotency_key,
        payload=payload,
        response_json=response_json,
        status_code=201,
        resource_type="assessment",
        resource_id=str(row.assessment_id),
    )
    db.commit()
    try_publish_event_rows(db, event_ids=[str(event.event_id)])
    return response_json


@router.get("/learners/{learner_id}/assessments", response_model=list[AssessmentResponse])
def list_assessments(
    learner_id: UUID,
    family_id: int = Query(..., ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    _learner_or_404(db, family_id=family_id, learner_id=learner_id)
    return [_serialize(AssessmentResponse, item) for item in recent_rows(db, Assessment, family_id=family_id, learner_id=learner_id, limit=limit, order_attr="occurred_at")]


@router.post("/practice-repetitions", response_model=PracticeRepetitionResponse, status_code=201)
def create_practice_repetition(
    payload: PracticeRepetitionCreate,
    db: Session = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=payload.family_id, actor_email=actor, internal_admin=internal_admin)
    ensure_seed_data(db)
    cached = consume_idempotency(db, family_id=payload.family_id, route_key="POST:/v1/practice-repetitions", idempotency_key=x_idempotency_key, payload=payload)
    if cached is not None:
        return cached
    _learner_or_404(db, family_id=payload.family_id, learner_id=payload.learner_id)
    _domain_or_404(db, payload.domain_id)
    _skill_or_404(db, payload.skill_id)
    row = PracticeRepetition(**payload.model_dump(), created_at=utcnow())
    db.add(row)
    db.flush()
    refresh_snapshots(db, family_id=row.family_id, learner_id=row.learner_id, domain_id=row.domain_id, skill_id=row.skill_id)
    actor_type, actor_id = normalize_actor(actor, internal_admin=internal_admin)
    event = create_event_log(
        db,
        family_id=row.family_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type="education.practice_repetition.recorded",
        entity_type="practice_repetition",
        entity_id=str(row.repetition_id),
        payload={"repetition_id": str(row.repetition_id), "learner_id": str(row.learner_id), "duration_seconds": row.duration_seconds, "performance_score": row.performance_score},
        idempotency_key=x_idempotency_key,
        contains_free_text=bool(row.notes),
    )
    response = _serialize(PracticeRepetitionResponse, row)
    response_json = jsonable_encoder(response)
    store_idempotency_result(
        db,
        family_id=row.family_id,
        route_key="POST:/v1/practice-repetitions",
        idempotency_key=x_idempotency_key,
        payload=payload,
        response_json=response_json,
        status_code=201,
        resource_type="practice_repetition",
        resource_id=str(row.repetition_id),
    )
    db.commit()
    try_publish_event_rows(db, event_ids=[str(event.event_id)])
    return response_json


@router.get("/learners/{learner_id}/practice-repetitions", response_model=list[PracticeRepetitionResponse])
def list_practice_repetitions(
    learner_id: UUID,
    family_id: int = Query(..., ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    _learner_or_404(db, family_id=family_id, learner_id=learner_id)
    return [_serialize(PracticeRepetitionResponse, item) for item in recent_rows(db, PracticeRepetition, family_id=family_id, learner_id=learner_id, limit=limit, order_attr="occurred_at")]


@router.post("/journals", response_model=JournalResponse, status_code=201)
def create_journal(
    payload: JournalCreate,
    db: Session = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=payload.family_id, actor_email=actor, internal_admin=internal_admin)
    cached = consume_idempotency(db, family_id=payload.family_id, route_key="POST:/v1/journals", idempotency_key=x_idempotency_key, payload=payload)
    if cached is not None:
        return cached
    _learner_or_404(db, family_id=payload.family_id, learner_id=payload.learner_id)
    row = JournalEntry(**payload.model_dump(), created_at=utcnow())
    db.add(row)
    db.flush()
    refresh_snapshots(db, family_id=row.family_id, learner_id=row.learner_id, domain_id=None, skill_id=None)
    actor_type, actor_id = normalize_actor(actor, internal_admin=internal_admin)
    event = create_event_log(
        db,
        family_id=row.family_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type="education.journal.recorded",
        entity_type="journal",
        entity_id=str(row.journal_id),
        payload={"journal_id": str(row.journal_id), "learner_id": str(row.learner_id), "title": row.title},
        idempotency_key=x_idempotency_key,
        contains_free_text=True,
    )
    response = _serialize(JournalResponse, row)
    response_json = jsonable_encoder(response)
    store_idempotency_result(
        db,
        family_id=row.family_id,
        route_key="POST:/v1/journals",
        idempotency_key=x_idempotency_key,
        payload=payload,
        response_json=response_json,
        status_code=201,
        resource_type="journal",
        resource_id=str(row.journal_id),
    )
    db.commit()
    try_publish_event_rows(db, event_ids=[str(event.event_id)])
    return response_json


@router.get("/learners/{learner_id}/journals", response_model=list[JournalResponse])
def list_journals(
    learner_id: UUID,
    family_id: int = Query(..., ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    _learner_or_404(db, family_id=family_id, learner_id=learner_id)
    return [_serialize(JournalResponse, item) for item in recent_rows(db, JournalEntry, family_id=family_id, learner_id=learner_id, limit=limit, order_attr="occurred_at")]


@router.post("/quizzes", response_model=QuizSessionResponse, status_code=201)
def create_quiz(
    payload: QuizCreate,
    db: Session = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=payload.family_id, actor_email=actor, internal_admin=internal_admin)
    ensure_seed_data(db)
    cached = consume_idempotency(db, family_id=payload.family_id, route_key="POST:/v1/quizzes", idempotency_key=x_idempotency_key, payload=payload)
    if cached is not None:
        return cached
    _learner_or_404(db, family_id=payload.family_id, learner_id=payload.learner_id)
    _domain_or_404(db, payload.domain_id)
    _skill_or_404(db, payload.skill_id)
    row = QuizSession(
        **payload.model_dump(exclude={"created_by"}),
        created_by=payload.created_by or (actor or "system"),
        created_at=utcnow(),
    )
    db.add(row)
    db.flush()
    actor_type, actor_id = normalize_actor(actor, internal_admin=internal_admin)
    event = create_event_log(
        db,
        family_id=row.family_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type="education.quiz.created",
        entity_type="quiz",
        entity_id=str(row.quiz_id),
        payload={"quiz_id": str(row.quiz_id), "learner_id": str(row.learner_id), "title": row.title, "delivery_mode": row.delivery_mode},
        idempotency_key=x_idempotency_key,
    )
    response = _serialize(QuizSessionResponse, row)
    response_json = jsonable_encoder(response)
    store_idempotency_result(
        db,
        family_id=row.family_id,
        route_key="POST:/v1/quizzes",
        idempotency_key=x_idempotency_key,
        payload=payload,
        response_json=response_json,
        status_code=201,
        resource_type="quiz",
        resource_id=str(row.quiz_id),
    )
    db.commit()
    try_publish_event_rows(db, event_ids=[str(event.event_id)])
    return response_json


@router.post("/quizzes/{quiz_id}/items", response_model=list[QuizItemResponse], status_code=201)
def add_quiz_items(
    quiz_id: UUID,
    payload: QuizItemsCreate,
    db: Session = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    quiz = _quiz_or_404(db, family_id=payload.family_id, quiz_id=quiz_id)
    _ensure_scope(family_id=quiz.family_id, actor_email=actor, internal_admin=internal_admin)
    cached = consume_idempotency(db, family_id=quiz.family_id, route_key=f"POST:/v1/quizzes/{quiz_id}/items", idempotency_key=x_idempotency_key, payload=payload)
    if cached is not None:
        return cached
    existing_positions = {item.position for item in db.execute(select(QuizItem).where(QuizItem.quiz_id == quiz_id)).scalars().all()}
    created: list[QuizItem] = []
    for item in payload.items:
        if item.position in existing_positions:
            raise_api_error(409, "quiz_item_position_conflict", "quiz item position already exists", {"position": item.position})
        existing_positions.add(item.position)
        row = QuizItem(family_id=quiz.family_id, quiz_id=quiz_id, created_at=utcnow(), **item.model_dump())
        db.add(row)
        created.append(row)
    db.flush()
    update_quiz_totals(db, quiz_id=quiz_id)
    response = [_serialize(QuizItemResponse, item) for item in created]
    response_json = jsonable_encoder(response)
    store_idempotency_result(
        db,
        family_id=quiz.family_id,
        route_key=f"POST:/v1/quizzes/{quiz_id}/items",
        idempotency_key=x_idempotency_key,
        payload=payload,
        response_json=response_json,
        status_code=201,
        resource_type="quiz_items",
        resource_id=str(quiz_id),
    )
    db.commit()
    return response_json


@router.post("/quizzes/{quiz_id}/responses", response_model=list[QuizResponseRecord], status_code=201)
def add_quiz_responses(
    quiz_id: UUID,
    payload: QuizResponsesCreate,
    db: Session = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    quiz = _quiz_or_404(db, family_id=payload.family_id, quiz_id=quiz_id)
    _ensure_scope(family_id=quiz.family_id, actor_email=actor, internal_admin=internal_admin)
    cached = consume_idempotency(db, family_id=quiz.family_id, route_key=f"POST:/v1/quizzes/{quiz_id}/responses", idempotency_key=x_idempotency_key, payload=payload)
    if cached is not None:
        return cached
    _learner_or_404(db, family_id=quiz.family_id, learner_id=payload.learner_id)
    created: list[QuizResponse] = []
    for item in payload.responses:
        quiz_item = db.get(QuizItem, item.quiz_item_id)
        if quiz_item is None or quiz_item.quiz_id != quiz_id:
            raise_api_error(404, "quiz_item_not_found", "quiz item not found for quiz", {"quiz_id": str(quiz_id), "quiz_item_id": str(item.quiz_item_id)})
        row = QuizResponse(
            family_id=quiz.family_id,
            quiz_id=quiz_id,
            learner_id=payload.learner_id,
            created_at=utcnow(),
            **item.model_dump(),
        )
        db.add(row)
        created.append(row)
    db.flush()
    update_quiz_totals(db, quiz_id=quiz_id)
    actor_type, actor_id = normalize_actor(actor, internal_admin=internal_admin)
    event = create_event_log(
        db,
        family_id=quiz.family_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type="education.quiz.response_recorded",
        entity_type="quiz",
        entity_id=str(quiz.quiz_id),
        payload={"quiz_id": str(quiz.quiz_id), "learner_id": str(payload.learner_id), "response_ids": [str(item.response_id) for item in created]},
        idempotency_key=x_idempotency_key,
    )
    response = [_serialize(QuizResponseRecord, item) for item in created]
    response_json = jsonable_encoder(response)
    store_idempotency_result(
        db,
        family_id=quiz.family_id,
        route_key=f"POST:/v1/quizzes/{quiz_id}/responses",
        idempotency_key=x_idempotency_key,
        payload=payload,
        response_json=response_json,
        status_code=201,
        resource_type="quiz_responses",
        resource_id=str(quiz.quiz_id),
    )
    db.commit()
    try_publish_event_rows(db, event_ids=[str(event.event_id)])
    return response_json


@router.get("/quizzes/{quiz_id}", response_model=QuizDetailResponse)
def get_quiz(
    quiz_id: UUID,
    family_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    quiz = _quiz_or_404(db, family_id=family_id, quiz_id=quiz_id)
    items = db.execute(select(QuizItem).where(QuizItem.quiz_id == quiz_id).order_by(QuizItem.position.asc())).scalars().all()
    responses = db.execute(select(QuizResponse).where(QuizResponse.quiz_id == quiz_id).order_by(QuizResponse.created_at.asc())).scalars().all()
    return QuizDetailResponse(
        session=_serialize(QuizSessionResponse, quiz),
        items=[_serialize(QuizItemResponse, item) for item in items],
        responses=[_serialize(QuizResponseRecord, item) for item in responses],
    )


@router.post("/attachments", response_model=AttachmentResponse, status_code=201)
def create_attachment(
    payload: AttachmentCreate,
    db: Session = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=payload.family_id, actor_email=actor, internal_admin=internal_admin)
    cached = consume_idempotency(db, family_id=payload.family_id, route_key="POST:/v1/attachments", idempotency_key=x_idempotency_key, payload=payload)
    if cached is not None:
        return cached
    _learner_or_404(db, family_id=payload.family_id, learner_id=payload.learner_id)
    row = Attachment(
        family_id=payload.family_id,
        learner_id=payload.learner_id,
        entity_type=payload.entity_type,
        entity_id=str(payload.entity_id),
        file_ref=payload.file_ref,
        mime_type=payload.mime_type,
        created_at=utcnow(),
    )
    db.add(row)
    db.flush()
    actor_type, actor_id = normalize_actor(actor, internal_admin=internal_admin)
    event = create_event_log(
        db,
        family_id=row.family_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type="education.attachment.linked",
        entity_type="attachment",
        entity_id=str(row.attachment_id),
        payload={"attachment_id": str(row.attachment_id), "learner_id": str(row.learner_id), "entity_type": row.entity_type, "entity_id": row.entity_id, "file_ref": row.file_ref},
        idempotency_key=x_idempotency_key,
    )
    response = _serialize(AttachmentResponse, row)
    response_json = jsonable_encoder(response)
    store_idempotency_result(
        db,
        family_id=row.family_id,
        route_key="POST:/v1/attachments",
        idempotency_key=x_idempotency_key,
        payload=payload,
        response_json=response_json,
        status_code=201,
        resource_type="attachment",
        resource_id=str(row.attachment_id),
    )
    db.commit()
    try_publish_event_rows(db, event_ids=[str(event.event_id)])
    return response_json


@router.get("/entities/{entity_type}/{entity_id}/attachments", response_model=list[AttachmentResponse])
def list_attachments(
    entity_type: str,
    entity_id: str,
    family_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    rows = db.execute(
        select(Attachment).where(
            Attachment.family_id == family_id,
            Attachment.entity_type == entity_type,
            Attachment.entity_id == entity_id,
        )
    ).scalars().all()
    return [_serialize(AttachmentResponse, item) for item in rows]


@router.get("/learners/{learner_id}/stats", response_model=StatsResponse)
def get_stats(
    learner_id: UUID,
    family_id: int = Query(..., ge=1),
    domain_id: UUID | None = Query(default=None),
    skill_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    _learner_or_404(db, family_id=family_id, learner_id=learner_id)
    return StatsResponse(**calculate_stats(db, family_id=family_id, learner_id=learner_id, domain_id=domain_id, skill_id=skill_id))


@router.get("/learners/{learner_id}/progress-snapshots", response_model=list[ProgressSnapshotResponse])
def list_progress_snapshots(
    learner_id: UUID,
    family_id: int = Query(..., ge=1),
    domain_id: UUID | None = Query(default=None),
    skill_id: UUID | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    _learner_or_404(db, family_id=family_id, learner_id=learner_id)
    query = select(ProgressSnapshot).where(ProgressSnapshot.family_id == family_id, ProgressSnapshot.learner_id == learner_id)
    if domain_id is not None:
        query = query.where(ProgressSnapshot.domain_id == domain_id)
    if skill_id is not None:
        query = query.where(ProgressSnapshot.skill_id == skill_id)
    rows = db.execute(query.order_by(ProgressSnapshot.as_of_date.desc()).limit(limit)).scalars().all()
    return [_serialize(ProgressSnapshotResponse, item) for item in rows]


@router.get("/learners/{learner_id}/education-summary", response_model=EducationSummaryResponse)
def get_education_summary(
    learner_id: UUID,
    family_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _caller_email(x_forwarded_user, x_dev_user)
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_scope(family_id=family_id, actor_email=actor, internal_admin=internal_admin)
    learner = _learner_or_404(db, family_id=family_id, learner_id=learner_id)
    goals = db.execute(
        select(LearningGoal).where(LearningGoal.family_id == family_id, LearningGoal.learner_id == learner_id, LearningGoal.status == "active").order_by(LearningGoal.created_at.desc()).limit(10)
    ).scalars().all()
    snapshots = db.execute(
        select(ProgressSnapshot).where(
            ProgressSnapshot.family_id == family_id,
            ProgressSnapshot.learner_id == learner_id,
            ProgressSnapshot.scope_key == "all",
        ).order_by(ProgressSnapshot.as_of_date.desc()).limit(5)
    ).scalars().all()
    return EducationSummaryResponse(
        learner=_serialize(LearnerResponse, learner),
        active_goals=[_serialize(GoalResponse, item) for item in goals],
        recent_activities=[_serialize(ActivityResponse, item) for item in recent_rows(db, LearningActivity, family_id=family_id, learner_id=learner_id, limit=10, order_attr="occurred_at")],
        recent_assignments=[_serialize(AssignmentResponse, item) for item in recent_rows(db, Assignment, family_id=family_id, learner_id=learner_id, limit=10)],
        recent_assessments=[_serialize(AssessmentResponse, item) for item in recent_rows(db, Assessment, family_id=family_id, learner_id=learner_id, limit=10, order_attr="occurred_at")],
        recent_practice_repetitions=[_serialize(PracticeRepetitionResponse, item) for item in recent_rows(db, PracticeRepetition, family_id=family_id, learner_id=learner_id, limit=10, order_attr="occurred_at")],
        recent_quiz_sessions=[_serialize(QuizSessionResponse, item) for item in recent_rows(db, QuizSession, family_id=family_id, learner_id=learner_id, limit=10)],
        latest_snapshots=[_serialize(ProgressSnapshotResponse, item) for item in snapshots],
        stats=StatsResponse(**calculate_stats(db, family_id=family_id, learner_id=learner_id)),
    )
