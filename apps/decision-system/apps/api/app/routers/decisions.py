from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.models.entities import (
    Decision,
    DecisionQueueItem,
    DecisionScoreComponent,
    DecisionScoreRun,
    DecisionStatusEnum,
    Goal,
    GoalPolicyEnum,
    ScopeTypeEnum,
    VisibilityScopeEnum,
)
from app.schemas.decisions import (
    DecisionCreate,
    DecisionGoalContextResponse,
    DecisionListResponse,
    DecisionResponse,
    DecisionScoreComponentResponse,
    DecisionScoreRequest,
    DecisionScoreResponse,
    DecisionScoreRunResponse,
    DecisionScoreRunsResponse,
    DecisionUpdate,
)
from app.schemas.goals import GoalResponse
from app.services.access import require_family_feature, require_family_member, require_person
from app.services.decision_domain import (
    active_goal_for_scoring,
    decision_visible_to_actor,
    ensure_person_decision_shape,
    goal_visible_to_actor,
    normalize_goal_policy,
    normalize_visibility,
    parse_person_id,
    resolve_actor_access_context,
    utc_now,
    validate_scoped_owner,
    validate_target_person,
)
from app.services.family_events import make_backend_event_payload
from app.services.memory import create_document_with_embeddings
from app.services.ops import record_agent_event
from app.services.scoring import GoalScoreInput, compute_weighted_score, threshold_outcome
from agents.common.family_events import diff_field_paths, make_privacy, publish_event as publish_family_event, snippet_fields

router = APIRouter(prefix="/v1/decisions", tags=["decisions"])
logger = logging.getLogger(__name__)


def _serialize_goal(goal: Goal) -> GoalResponse:
    return GoalResponse(
        id=goal.id,
        family_id=goal.family_id,
        scope_type=goal.scope_type,
        owner_person_id=str(goal.owner_person_id) if goal.owner_person_id is not None else None,
        visibility_scope=goal.visibility_scope,
        name=goal.name,
        description=goal.description,
        weight=goal.weight,
        action_types=list(goal.action_types_json or []),
        status=goal.status,
        priority=goal.priority,
        horizon=goal.horizon,
        target_date=goal.target_date,
        success_criteria=goal.success_criteria,
        review_cadence_days=goal.review_cadence_days,
        next_review_at=goal.next_review_at,
        tags=list(goal.tags_json or []),
        external_refs=list(goal.external_refs_json or []),
        goal_revision=goal.goal_revision,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
        deleted_at=goal.deleted_at,
    )


def _serialize_score_component(component: DecisionScoreComponent) -> DecisionScoreComponentResponse:
    return DecisionScoreComponentResponse(
        id=component.id,
        goal_id=component.goal_id,
        goal_name=component.goal_name,
        goal_scope_type=component.goal_scope_type,
        goal_owner_person_id=str(component.goal_owner_person_id) if component.goal_owner_person_id is not None else None,
        goal_revision=component.goal_revision,
        goal_weight=component.goal_weight,
        score_1_to_5=component.score_1_to_5,
        rationale=component.rationale,
        created_at=component.created_at,
    )


def _score_components_for_run(db: Session, score_run_id: int) -> list[DecisionScoreComponent]:
    return db.execute(
        select(DecisionScoreComponent)
        .where(DecisionScoreComponent.score_run_id == score_run_id)
        .order_by(DecisionScoreComponent.goal_scope_type.asc(), DecisionScoreComponent.goal_name.asc(), DecisionScoreComponent.id.asc())
    ).scalars().all()


def _serialize_score_run(db: Session, score_run: DecisionScoreRun | None) -> DecisionScoreRunResponse | None:
    if score_run is None:
        return None
    components = _score_components_for_run(db, score_run.id)
    return DecisionScoreRunResponse(
        id=score_run.id,
        decision_id=score_run.decision_id,
        family_id=score_run.family_id,
        scored_by_person_id=str(score_run.scored_by_person_id) if score_run.scored_by_person_id is not None else None,
        computed_by=score_run.computed_by,
        decision_version=score_run.decision_version,
        goal_policy=score_run.goal_policy,
        threshold_1_to_5=score_run.threshold_1_to_5,
        family_weighted_total_1_to_5=score_run.family_weighted_total_1_to_5,
        family_weighted_total_0_to_100=score_run.family_weighted_total_0_to_100,
        person_weighted_total_1_to_5=score_run.person_weighted_total_1_to_5,
        person_weighted_total_0_to_100=score_run.person_weighted_total_0_to_100,
        weighted_total_1_to_5=score_run.weighted_total_1_to_5,
        weighted_total_0_to_100=score_run.weighted_total_0_to_100,
        routed_to=score_run.routed_to,
        status_after_run=score_run.status_after_run,
        context_snapshot=dict(score_run.context_snapshot_json or {}),
        created_at=score_run.created_at,
        components=[_serialize_score_component(component) for component in components],
    )


def _latest_score_run(db: Session, decision_id: int) -> DecisionScoreRun | None:
    return db.execute(
        select(DecisionScoreRun)
        .where(DecisionScoreRun.decision_id == decision_id)
        .order_by(DecisionScoreRun.created_at.desc(), DecisionScoreRun.id.desc())
    ).scalar_one_or_none()


def _serialize_decision(db: Session, decision: Decision, *, include_scores: bool) -> DecisionResponse:
    latest = _latest_score_run(db, decision.id) if include_scores else None
    return DecisionResponse(
        id=decision.id,
        family_id=decision.family_id,
        scope_type=decision.scope_type,
        created_by_person_id=str(decision.created_by_person_id),
        owner_person_id=str(decision.owner_person_id) if decision.owner_person_id is not None else None,
        target_person_id=str(decision.target_person_id) if decision.target_person_id is not None else None,
        visibility_scope=decision.visibility_scope,
        goal_policy=decision.goal_policy,
        category=decision.category,
        title=decision.title,
        description=decision.description,
        desired_outcome=decision.desired_outcome,
        constraints=list(decision.constraints_json or []),
        options=list(decision.options_json or []),
        cost=decision.cost,
        urgency=decision.urgency,
        confidence_1_to_5=decision.confidence_1_to_5,
        target_date=decision.target_date,
        next_review_at=decision.next_review_at,
        tags=list(decision.tags_json or []),
        status=decision.status,
        notes=decision.notes,
        attachments=list(decision.attachments_json or []),
        links=list(decision.links_json or []),
        context_snapshot=dict(decision.context_snapshot_json or {}),
        version=decision.version,
        created_at=decision.created_at,
        updated_at=decision.updated_at,
        completed_at=decision.completed_at,
        deleted_at=decision.deleted_at,
        latest_score_run=_serialize_score_run(db, latest),
    )


def _decision_state(decision: Decision) -> dict[str, Any]:
    return {
        "scope_type": decision.scope_type.value,
        "created_by_person_id": str(decision.created_by_person_id),
        "owner_person_id": str(decision.owner_person_id) if decision.owner_person_id is not None else None,
        "target_person_id": str(decision.target_person_id) if decision.target_person_id is not None else None,
        "visibility_scope": decision.visibility_scope.value,
        "goal_policy": decision.goal_policy.value,
        "category": decision.category,
        "title": decision.title,
        "description": decision.description,
        "desired_outcome": decision.desired_outcome,
        "constraints": list(decision.constraints_json or []),
        "options": list(decision.options_json or []),
        "cost": decision.cost,
        "urgency": decision.urgency,
        "confidence_1_to_5": decision.confidence_1_to_5,
        "target_date": decision.target_date.isoformat() if decision.target_date else None,
        "next_review_at": decision.next_review_at.isoformat() if decision.next_review_at else None,
        "tags": list(decision.tags_json or []),
        "status": decision.status.value,
        "notes": decision.notes,
        "attachments": list(decision.attachments_json or []),
        "links": list(decision.links_json or []),
        "context_snapshot": dict(decision.context_snapshot_json or {}),
        "version": decision.version,
        "completed_at": decision.completed_at.isoformat() if decision.completed_at else None,
        "deleted_at": decision.deleted_at.isoformat() if decision.deleted_at else None,
    }


def _decision_payload(decision: Decision, *, changed_fields: list[str] | None = None, extra_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "decision_id": decision.id,
        "scope_type": decision.scope_type.value,
        "created_by_person_id": str(decision.created_by_person_id),
        "owner_person_id": str(decision.owner_person_id) if decision.owner_person_id is not None else None,
        "target_person_id": str(decision.target_person_id) if decision.target_person_id is not None else None,
        "visibility_scope": decision.visibility_scope.value,
        "goal_policy": decision.goal_policy.value,
        "category": decision.category,
        "cost": decision.cost,
        "urgency": decision.urgency,
        "confidence_1_to_5": decision.confidence_1_to_5,
        "target_date": decision.target_date.isoformat() if decision.target_date else None,
        "next_review_at": decision.next_review_at.isoformat() if decision.next_review_at else None,
        "status": decision.status.value,
        "version": decision.version,
        "constraint_count": len(decision.constraints_json or []),
        "option_count": len(decision.options_json or []),
        "tag_count": len(decision.tags_json or []),
        "attachment_count": len(decision.attachments_json or []),
        "link_count": len(decision.links_json or []),
        "context_keys": sorted(str(key) for key in (decision.context_snapshot_json or {})),
    }
    if changed_fields:
        payload["changed_fields"] = changed_fields
    if extra_payload:
        payload.update({key: value for key, value in extra_payload.items() if value is not None})
    payload.update(snippet_fields("title", decision.title))
    payload.update(snippet_fields("description", decision.description))
    payload.update(snippet_fields("desired_outcome", decision.desired_outcome))
    payload.update(snippet_fields("notes", decision.notes))
    payload["title"] = payload.get("title_snippet") or f"Decision {decision.id}"
    return payload


def _emit_decision_event(
    *,
    decision: Decision,
    actor_id: str,
    actor_person_id: str | None,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    subject_person_id = decision.target_person_id or decision.owner_person_id or decision.created_by_person_id
    event = make_backend_event_payload(
        family_id=decision.family_id,
        domain="decision",
        event_type=event_type,
        actor_id=actor_id,
        actor_type="user",
        actor_person_id=actor_person_id,
        subject_id=str(decision.id),
        subject_type="decision",
        subject_person_id=str(subject_person_id) if subject_person_id is not None else None,
        payload=payload,
        source_agent_id="DecisionAgent",
        source_runtime="backend",
        tags=list(decision.tags_json or []),
        privacy=make_privacy(
            contains_pii=bool(subject_person_id),
            contains_child_data=bool(subject_person_id),
            contains_free_text=any(key.endswith("_snippet") for key in payload),
        ),
    )
    publish_family_event(event)


def _require_decision(db: Session, decision_id: int) -> Decision:
    decision = db.get(Decision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="decision not found")
    return decision


def _applicable_goals(db: Session, decision: Decision) -> tuple[list[Goal], list[Goal], list[dict[str, Any]]]:
    family_goals = db.execute(
        select(Goal).where(
            Goal.family_id == decision.family_id,
            Goal.scope_type == ScopeTypeEnum.family,
            Goal.deleted_at.is_(None),
        )
    ).scalars().all()
    family_goals = [goal for goal in family_goals if active_goal_for_scoring(goal)]

    person_goals: list[Goal] = []
    if decision.goal_policy == GoalPolicyEnum.family_plus_person and decision.target_person_id is not None:
        person_goals = db.execute(
            select(Goal).where(
                Goal.family_id == decision.family_id,
                Goal.scope_type == ScopeTypeEnum.person,
                Goal.owner_person_id == decision.target_person_id,
                Goal.deleted_at.is_(None),
            )
        ).scalars().all()
        person_goals = [goal for goal in person_goals if active_goal_for_scoring(goal)]

    external_context = list(decision.context_snapshot_json.get("external_context", [])) if isinstance(decision.context_snapshot_json, dict) else []
    for goal in family_goals + person_goals:
        for ref in goal.external_refs_json or []:
            external_context.append(ref)
    return family_goals, person_goals, external_context


def _goal_context_response(db: Session, decision: Decision) -> DecisionGoalContextResponse:
    family_goals, person_goals, external_context = _applicable_goals(db, decision)
    return DecisionGoalContextResponse(
        decision_id=decision.id,
        family_id=decision.family_id,
        scope_type=decision.scope_type,
        goal_policy=decision.goal_policy,
        target_person_id=str(decision.target_person_id) if decision.target_person_id is not None else None,
        family_goals=[_serialize_goal(goal) for goal in family_goals],
        person_goals=[_serialize_goal(goal) for goal in person_goals],
        external_context=external_context,
    )


def _decision_budget_person_id(decision: Decision) -> str:
    selected = decision.owner_person_id or decision.target_person_id or decision.created_by_person_id
    return str(selected)


def _upsert_queue_item(db: Session, decision: Decision) -> DecisionQueueItem:
    queue_item = db.execute(
        select(DecisionQueueItem).where(DecisionQueueItem.decision_id == decision.id)
    ).scalar_one_or_none()
    if queue_item is None:
        max_rank = db.execute(select(func.max(DecisionQueueItem.rank))).scalar_one()
        queue_item = DecisionQueueItem(
            decision_id=decision.id,
            priority=decision.urgency or 3,
            due_date=decision.target_date,
            rank=(max_rank or 0) + 1,
        )
        db.add(queue_item)
        db.flush()
    else:
        queue_item.priority = decision.urgency or 3
        queue_item.due_date = decision.target_date
    return queue_item


@router.get("", response_model=DecisionListResponse)
def list_decisions(
    family_id: int = Query(...),
    scope_type: ScopeTypeEnum | None = Query(default=None),
    owner_person_id: str | None = Query(default=None),
    target_person_id: str | None = Query(default=None),
    visibility_scope: VisibilityScopeEnum | None = Query(default=None),
    goal_policy: GoalPolicyEnum | None = Query(default=None),
    status: DecisionStatusEnum | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    include_scores: bool = Query(default=False),
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family_feature(db, family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user)
    query = select(Decision).where(Decision.family_id == family_id)
    if scope_type is not None:
        query = query.where(Decision.scope_type == scope_type)
    if owner_person_id is not None:
        query = query.where(Decision.owner_person_id == parse_person_id(owner_person_id))
    if target_person_id is not None:
        query = query.where(Decision.target_person_id == parse_person_id(target_person_id))
    if visibility_scope is not None:
        query = query.where(Decision.visibility_scope == visibility_scope)
    if goal_policy is not None:
        query = query.where(Decision.goal_policy == goal_policy)
    if status is not None:
        query = query.where(Decision.status == status)
    if not include_deleted:
        query = query.where(Decision.deleted_at.is_(None))
    rows = db.execute(query.order_by(Decision.updated_at.desc(), Decision.id.desc())).scalars().all()
    items = [
        _serialize_decision(db, row, include_scores=include_scores)
        for row in rows
        if decision_visible_to_actor(
            row,
            actor_person_id=actor.actor_person_id,
            is_family_admin=actor.is_family_admin,
            include_deleted=include_deleted,
        )
    ]
    return DecisionListResponse(items=items)


@router.get("/{decision_id}", response_model=DecisionResponse)
def get_decision(
    decision_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    decision = _require_decision(db, decision_id)
    require_family_feature(db, decision.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=decision.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if not decision_visible_to_actor(decision, actor_person_id=actor.actor_person_id, is_family_admin=actor.is_family_admin):
        raise HTTPException(status_code=403, detail="decision is not visible to this actor")
    return _serialize_decision(db, decision, include_scores=True)


@router.get("/{decision_id}/goal-context", response_model=DecisionGoalContextResponse)
def get_decision_goal_context(
    decision_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    decision = _require_decision(db, decision_id)
    require_family_feature(db, decision.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=decision.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if not decision_visible_to_actor(decision, actor_person_id=actor.actor_person_id, is_family_admin=actor.is_family_admin):
        raise HTTPException(status_code=403, detail="decision is not visible to this actor")
    return _goal_context_response(db, decision)


@router.get("/{decision_id}/score-runs", response_model=DecisionScoreRunsResponse)
def list_decision_score_runs(
    decision_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    decision = _require_decision(db, decision_id)
    require_family_feature(db, decision.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=decision.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if not decision_visible_to_actor(decision, actor_person_id=actor.actor_person_id, is_family_admin=actor.is_family_admin):
        raise HTTPException(status_code=403, detail="decision is not visible to this actor")
    runs = db.execute(
        select(DecisionScoreRun)
        .where(DecisionScoreRun.decision_id == decision_id)
        .order_by(DecisionScoreRun.created_at.desc(), DecisionScoreRun.id.desc())
    ).scalars().all()
    return DecisionScoreRunsResponse(items=[_serialize_score_run(db, run) for run in runs if run is not None])


@router.post("", response_model=DecisionResponse, status_code=201)
def create_decision(
    payload: DecisionCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family_feature(db, payload.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=payload.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if ctx is not None or x_dev_user:
        require_family_member(db, payload.family_id, actor.actor_id)

    created_by_person_id = actor.actor_person_id or payload.created_by_person_id
    if created_by_person_id is None:
        raise HTTPException(status_code=400, detail="created_by_person_id is required when actor identity is unavailable")
    created_by_person = require_person(db, payload.family_id, created_by_person_id, field_name="created_by_person_id")
    owner = validate_scoped_owner(
        db,
        family_id=payload.family_id,
        scope_type=payload.scope_type,
        owner_person_id=payload.owner_person_id,
        required_for_person_scope=False,
    )
    target = validate_target_person(db, family_id=payload.family_id, target_person_id=payload.target_person_id)
    normalized_goal_policy = normalize_goal_policy(payload.scope_type, payload.goal_policy)
    ensure_person_decision_shape(
        scope_type=payload.scope_type,
        target_person_id=str(target.person_id) if target is not None else None,
        goal_policy=normalized_goal_policy,
    )
    if not actor.is_family_admin and actor.actor_person_id is not None:
        personal_targets = {value for value in {str(created_by_person.person_id), str(owner.person_id) if owner else None, str(target.person_id) if target else None} if value is not None}
        if any(person_id != actor.actor_person_id for person_id in personal_targets):
            raise HTTPException(status_code=403, detail="cross-person decision creation requires a family admin")

    now = utc_now()
    decision = Decision(
        family_id=payload.family_id,
        scope_type=payload.scope_type,
        created_by_person_id=created_by_person.person_id,
        owner_person_id=owner.person_id if owner is not None else None,
        target_person_id=target.person_id if target is not None else None,
        visibility_scope=normalize_visibility(payload.scope_type, payload.visibility_scope),
        goal_policy=normalized_goal_policy,
        category=payload.category,
        title=payload.title,
        description=payload.description,
        desired_outcome=payload.desired_outcome,
        constraints_json=payload.constraints,
        options_json=payload.options,
        cost=payload.cost,
        urgency=payload.urgency,
        confidence_1_to_5=payload.confidence_1_to_5,
        target_date=payload.target_date,
        next_review_at=payload.next_review_at,
        tags_json=payload.tags,
        notes=payload.notes,
        attachments_json=payload.attachments,
        links_json=payload.links,
        context_snapshot_json=payload.context_snapshot,
        status=DecisionStatusEnum.draft,
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    try:
        create_document_with_embeddings(
            db,
            family_id=decision.family_id,
            type="decision",
            text_value=f"Decision created: {decision.title}\n\n{decision.description}",
            source_refs=[],
        )
        db.commit()
    except Exception:
        logger.exception("Failed to index created decision in memory for decision_id=%s", decision.id)
        db.rollback()
    try:
        _emit_decision_event(
            decision=decision,
            actor_id=actor.actor_id,
            actor_person_id=actor.actor_person_id,
            event_type="decision.created",
            payload=_decision_payload(decision),
        )
    except Exception:
        logger.exception("Failed to emit decision.created for decision_id=%s", decision.id)
    record_agent_event(
        db,
        family_id=decision.family_id,
        domain="decision",
        source_agent="decision-api.decisions",
        actor=actor.actor_id,
        event_type="decision_created",
        summary=f"Decision created: {decision.title}",
        topic=decision.title,
        status=decision.status.value,
        payload={
            "decision_id": decision.id,
            "scope_type": decision.scope_type.value,
            "target_person_id": str(decision.target_person_id) if decision.target_person_id is not None else None,
        },
        emit_canonical=False,
    )
    db.commit()
    return _serialize_decision(db, decision, include_scores=True)


@router.patch("/{decision_id}", response_model=DecisionResponse)
def update_decision(
    decision_id: int,
    payload: DecisionUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    decision = _require_decision(db, decision_id)
    require_family_feature(db, decision.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=decision.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if ctx is not None or x_dev_user:
        require_family_member(db, decision.family_id, actor.actor_id)
    if not decision_visible_to_actor(decision, actor_person_id=actor.actor_person_id, is_family_admin=actor.is_family_admin):
        raise HTTPException(status_code=403, detail="decision is not editable by this actor")

    next_scope = payload.scope_type or decision.scope_type
    next_owner_person_id = payload.owner_person_id if payload.owner_person_id is not None else (str(decision.owner_person_id) if decision.owner_person_id is not None else None)
    next_target_person_id = payload.target_person_id if payload.target_person_id is not None else (str(decision.target_person_id) if decision.target_person_id is not None else None)
    owner = validate_scoped_owner(
        db,
        family_id=decision.family_id,
        scope_type=next_scope,
        owner_person_id=next_owner_person_id,
        required_for_person_scope=False,
    )
    target = validate_target_person(db, family_id=decision.family_id, target_person_id=next_target_person_id)
    normalized_goal_policy = normalize_goal_policy(next_scope, payload.goal_policy or decision.goal_policy)
    ensure_person_decision_shape(
        scope_type=next_scope,
        target_person_id=str(target.person_id) if target is not None else None,
        goal_policy=normalized_goal_policy,
    )

    if not actor.is_family_admin and actor.actor_person_id is not None:
        assigned_people = {
            value
            for value in {
                str(owner.person_id) if owner is not None else None,
                str(target.person_id) if target is not None else None,
            }
            if value is not None
        }
        if any(person_id != actor.actor_person_id for person_id in assigned_people):
            raise HTTPException(status_code=403, detail="cross-person decision updates require a family admin")

    before_state = _decision_state(decision)
    changed = False
    next_visibility = normalize_visibility(
        next_scope,
        payload.visibility_scope if payload.visibility_scope is not None else (None if payload.scope_type is not None else decision.visibility_scope),
    )
    if decision.scope_type != next_scope:
        decision.scope_type = next_scope
        changed = True
    new_owner = owner.person_id if owner is not None else None
    if decision.owner_person_id != new_owner:
        decision.owner_person_id = new_owner
        changed = True
    new_target = target.person_id if target is not None else None
    if decision.target_person_id != new_target:
        decision.target_person_id = new_target
        changed = True
    if decision.visibility_scope != next_visibility:
        decision.visibility_scope = next_visibility
        changed = True
    if decision.goal_policy != normalized_goal_policy:
        decision.goal_policy = normalized_goal_policy
        changed = True
    for field in ("category", "title", "description", "desired_outcome", "cost", "urgency", "confidence_1_to_5", "target_date", "next_review_at", "notes"):
        value = getattr(payload, field)
        if value is not None and getattr(decision, field) != value:
            setattr(decision, field, value)
            changed = True
    if payload.constraints is not None and decision.constraints_json != payload.constraints:
        decision.constraints_json = payload.constraints
        changed = True
    if payload.options is not None and decision.options_json != payload.options:
        decision.options_json = payload.options
        changed = True
    if payload.tags is not None and decision.tags_json != payload.tags:
        decision.tags_json = payload.tags
        changed = True
    if payload.attachments is not None and decision.attachments_json != payload.attachments:
        decision.attachments_json = payload.attachments
        changed = True
    if payload.links is not None and decision.links_json != payload.links:
        decision.links_json = payload.links
        changed = True
    if payload.context_snapshot is not None and decision.context_snapshot_json != payload.context_snapshot:
        decision.context_snapshot_json = payload.context_snapshot
        changed = True

    if changed:
        decision.version += 1
    decision.updated_at = utc_now()
    db.commit()
    db.refresh(decision)
    try:
        create_document_with_embeddings(
            db,
            family_id=decision.family_id,
            type="decision",
            text_value=f"Decision updated: {decision.title}\n\n{decision.description}",
            source_refs=[],
        )
        db.commit()
    except Exception:
        logger.exception("Failed to index updated decision in memory for decision_id=%s", decision.id)
        db.rollback()
    try:
        _emit_decision_event(
            decision=decision,
            actor_id=actor.actor_id,
            actor_person_id=actor.actor_person_id,
            event_type="decision.updated",
            payload=_decision_payload(decision, changed_fields=diff_field_paths(before_state, _decision_state(decision))),
        )
    except Exception:
        logger.exception("Failed to emit decision.updated for decision_id=%s", decision.id)
    record_agent_event(
        db,
        family_id=decision.family_id,
        domain="decision",
        source_agent="decision-api.decisions",
        actor=actor.actor_id,
        event_type="decision_updated",
        summary=f"Decision updated: {decision.title}",
        topic=decision.title,
        status=decision.status.value,
        payload={"decision_id": decision.id, "version": decision.version},
        emit_canonical=False,
    )
    db.commit()
    return _serialize_decision(db, decision, include_scores=True)


@router.delete("/{decision_id}", status_code=204)
def delete_decision(
    decision_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    decision = _require_decision(db, decision_id)
    require_family_feature(db, decision.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=decision.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if ctx is not None or x_dev_user:
        require_family_member(db, decision.family_id, actor.actor_id)
    if not decision_visible_to_actor(decision, actor_person_id=actor.actor_person_id, is_family_admin=actor.is_family_admin):
        raise HTTPException(status_code=403, detail="decision is not deletable by this actor")

    now = utc_now()
    decision.deleted_at = now
    decision.updated_at = now
    decision.status = DecisionStatusEnum.archived
    db.execute(delete(DecisionQueueItem).where(DecisionQueueItem.decision_id == decision.id))
    db.commit()
    try:
        _emit_decision_event(
            decision=decision,
            actor_id=actor.actor_id,
            actor_person_id=actor.actor_person_id,
            event_type="decision.deleted",
            payload=_decision_payload(decision, changed_fields=["status", "deleted_at", "updated_at"]),
        )
    except Exception:
        logger.exception("Failed to emit decision.deleted for decision_id=%s", decision.id)
    record_agent_event(
        db,
        family_id=decision.family_id,
        domain="decision",
        source_agent="decision-api.decisions",
        actor=actor.actor_id,
        event_type="decision_deleted",
        summary=f"Decision deleted: {decision.title}",
        topic=decision.title,
        status="deleted",
        payload={"decision_id": decision.id},
        emit_canonical=False,
    )
    db.commit()


@router.post("/{decision_id}/score", response_model=DecisionScoreResponse)
def manual_score_decision(
    decision_id: int,
    payload: DecisionScoreRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    decision = _require_decision(db, decision_id)
    if decision.deleted_at is not None:
        raise HTTPException(status_code=400, detail="cannot score a deleted decision")
    require_family_feature(db, decision.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=decision.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if ctx is not None or x_dev_user:
        require_family_member(db, decision.family_id, actor.actor_id)
    if not decision_visible_to_actor(decision, actor_person_id=actor.actor_person_id, is_family_admin=actor.is_family_admin):
        raise HTTPException(status_code=403, detail="decision is not visible to this actor")

    scoring_person_id = payload.scored_by_person_id or actor.actor_person_id
    if payload.scored_by_person_id is not None:
        require_person(db, decision.family_id, payload.scored_by_person_id, field_name="scored_by_person_id")

    family_goals, person_goals, external_context = _applicable_goals(db, decision)
    applicable_goals = family_goals + person_goals
    goal_map = {goal.id: goal for goal in applicable_goals}

    provided_goal_ids = [item.goal_id for item in payload.goal_scores]
    expected_goal_ids = set(goal_map)
    provided_goal_ids_set = set(provided_goal_ids)
    if expected_goal_ids != provided_goal_ids_set:
        missing = sorted(expected_goal_ids - provided_goal_ids_set)
        extra = sorted(provided_goal_ids_set - expected_goal_ids)
        raise HTTPException(
            status_code=400,
            detail={
                "message": "goal scores must match the active goal context exactly",
                "missing_goal_ids": missing,
                "extra_goal_ids": extra,
            },
        )
    if len(provided_goal_ids) != len(provided_goal_ids_set):
        raise HTTPException(status_code=400, detail="goal_scores cannot contain duplicate goal ids")

    family_inputs: list[GoalScoreInput] = []
    person_inputs: list[GoalScoreInput] = []
    for item in payload.goal_scores:
        goal = goal_map[item.goal_id]
        score_input = GoalScoreInput(weight=goal.weight, score=item.score_1_to_5)
        if goal.scope_type == ScopeTypeEnum.family:
            family_inputs.append(score_input)
        else:
            person_inputs.append(score_input)

    weighted_inputs = family_inputs + person_inputs
    weighted_1_to_5 = compute_weighted_score(weighted_inputs, normalize_to=5)
    weighted_0_to_100 = compute_weighted_score(weighted_inputs, normalize_to=100)
    family_weighted_1_to_5 = compute_weighted_score(family_inputs, normalize_to=5) if family_inputs else None
    family_weighted_0_to_100 = compute_weighted_score(family_inputs, normalize_to=100) if family_inputs else None
    person_weighted_1_to_5 = compute_weighted_score(person_inputs, normalize_to=5) if person_inputs else None
    person_weighted_0_to_100 = compute_weighted_score(person_inputs, normalize_to=100) if person_inputs else None
    routed_to = threshold_outcome(weighted_1_to_5, payload.threshold_1_to_5)

    queue_item_id: int | None = None
    if routed_to == "queue":
        decision.status = DecisionStatusEnum.queued
        queue_item = _upsert_queue_item(db, decision)
        queue_item_id = queue_item.id
    else:
        decision.status = DecisionStatusEnum.needs_work
        db.execute(delete(DecisionQueueItem).where(DecisionQueueItem.decision_id == decision.id))

    decision.updated_at = utc_now()
    score_run = DecisionScoreRun(
        decision_id=decision.id,
        family_id=decision.family_id,
        scored_by_person_id=parse_person_id(scoring_person_id),
        computed_by=payload.computed_by,
        decision_version=decision.version,
        goal_policy=decision.goal_policy,
        threshold_1_to_5=payload.threshold_1_to_5,
        family_weighted_total_1_to_5=family_weighted_1_to_5,
        family_weighted_total_0_to_100=family_weighted_0_to_100,
        person_weighted_total_1_to_5=person_weighted_1_to_5,
        person_weighted_total_0_to_100=person_weighted_0_to_100,
        weighted_total_1_to_5=weighted_1_to_5,
        weighted_total_0_to_100=weighted_0_to_100,
        routed_to=routed_to,
        status_after_run=decision.status.value,
        context_snapshot_json={
            "decision_context": dict(decision.context_snapshot_json or {}),
            "provided_context": payload.context_snapshot,
            "external_context": external_context,
        },
        created_at=utc_now(),
    )
    db.add(score_run)
    db.flush()

    for item in payload.goal_scores:
        goal = goal_map[item.goal_id]
        db.add(
            DecisionScoreComponent(
                score_run_id=score_run.id,
                decision_id=decision.id,
                goal_id=goal.id,
                goal_scope_type=goal.scope_type,
                goal_owner_person_id=goal.owner_person_id,
                goal_revision=goal.goal_revision,
                goal_name=goal.name,
                goal_weight=goal.weight,
                score_1_to_5=item.score_1_to_5,
                rationale=item.rationale,
                created_at=utc_now(),
            )
        )

    db.commit()
    db.refresh(score_run)
    try:
        create_document_with_embeddings(
            db,
            family_id=decision.family_id,
            type="rationale",
            text_value=f"Decision scored: decision_id={decision.id} weighted_1_to_5={weighted_1_to_5} threshold={payload.threshold_1_to_5} routed_to={routed_to}",
            source_refs=[],
        )
        db.commit()
    except Exception:
        logger.exception("Failed to index scored decision rationale for decision_id=%s", decision.id)
        db.rollback()

    score_payload = _decision_payload(
        decision,
        extra_payload={
        "score_type": "goal_alignment",
        "score_value": weighted_1_to_5,
        "threshold_1_to_5": payload.threshold_1_to_5,
        "routed_to": routed_to,
        "score_run_id": score_run.id,
            "component_count": len(payload.goal_scores),
            "family_weighted_total_1_to_5": family_weighted_1_to_5,
            "person_weighted_total_1_to_5": person_weighted_1_to_5,
            "family_weighted_total_0_to_100": family_weighted_0_to_100,
            "person_weighted_total_0_to_100": person_weighted_0_to_100,
            "goal_score_inputs": [
                {"goal_id": item.goal_id, "score_1_to_5": item.score_1_to_5}
                for item in payload.goal_scores
            ],
        },
    )
    try:
        _emit_decision_event(
            decision=decision,
            actor_id=actor.actor_id,
            actor_person_id=actor.actor_person_id,
            event_type="decision.score_calculated",
            payload=score_payload,
        )
        _emit_decision_event(
            decision=decision,
            actor_id=actor.actor_id,
            actor_person_id=actor.actor_person_id,
            event_type="decision.score_above_threshold" if weighted_1_to_5 >= payload.threshold_1_to_5 else "decision.score_below_threshold",
            payload=score_payload,
        )
    except Exception:
        logger.exception("Failed to emit decision score events for decision_id=%s score_run_id=%s", decision.id, score_run.id)
    record_agent_event(
        db,
        family_id=decision.family_id,
        domain="decision",
        source_agent="decision-api.decisions",
        actor=actor.actor_id,
        event_type="decision_score_calculated",
        summary=f"Decision scored: {decision.title}",
        topic=decision.title,
        status=decision.status.value,
        value_number=weighted_1_to_5,
        payload={
            "decision_id": decision.id,
            "threshold_1_to_5": payload.threshold_1_to_5,
            "routed_to": routed_to,
            "score_run_id": score_run.id,
        },
        emit_canonical=False,
    )
    record_agent_event(
        db,
        family_id=decision.family_id,
        domain="decision",
        source_agent="decision-api.decisions",
        actor=actor.actor_id,
        event_type="decision_score_above_threshold" if weighted_1_to_5 >= payload.threshold_1_to_5 else "decision_score_below_threshold",
        summary=("Decision above threshold: " if weighted_1_to_5 >= payload.threshold_1_to_5 else "Decision below threshold: ") + decision.title,
        topic=decision.title,
        status=decision.status.value,
        value_number=weighted_1_to_5,
        payload={"decision_id": decision.id, "threshold_1_to_5": payload.threshold_1_to_5, "score_run_id": score_run.id},
        emit_canonical=False,
    )
    db.commit()

    return DecisionScoreResponse(
        decision_id=decision.id,
        weighted_total_1_to_5=weighted_1_to_5,
        weighted_total_0_to_100=weighted_0_to_100,
        threshold_1_to_5=payload.threshold_1_to_5,
        routed_to=routed_to,
        status=decision.status.value,
        queue_item_id=queue_item_id,
        score_run=_serialize_score_run(db, score_run),
    )


@router.post("/{decision_id}/queue")
def queue_decision(
    decision_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    decision = _require_decision(db, decision_id)
    require_family_feature(db, decision.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=decision.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if ctx is not None or x_dev_user:
        require_family_member(db, decision.family_id, actor.actor_id)
    if not decision_visible_to_actor(decision, actor_person_id=actor.actor_person_id, is_family_admin=actor.is_family_admin):
        raise HTTPException(status_code=403, detail="decision is not editable by this actor")

    queue_item = _upsert_queue_item(db, decision)
    decision.status = DecisionStatusEnum.queued
    decision.updated_at = utc_now()
    db.commit()
    db.refresh(queue_item)
    try:
        _emit_decision_event(
            decision=decision,
            actor_id=actor.actor_id,
            actor_person_id=actor.actor_person_id,
            event_type="decision.updated",
            payload=_decision_payload(decision, changed_fields=["status"], extra_payload={"queue_item_id": queue_item.id}),
        )
    except Exception:
        logger.exception("Failed to emit decision.updated(queue) for decision_id=%s", decision.id)
    record_agent_event(
        db,
        family_id=decision.family_id,
        domain="decision",
        source_agent="decision-api.decisions",
        actor=actor.actor_id,
        event_type="decision_queued",
        summary=f"Decision queued: {decision.title}",
        topic=decision.title,
        status=decision.status.value,
        payload={"decision_id": decision.id, "queue_item_id": queue_item.id},
        emit_canonical=False,
    )
    db.commit()
    return {"decision_id": decision_id, "status": "queued", "queue_item_id": queue_item.id}


@router.post("/{decision_id}/status")
def update_status(
    decision_id: int,
    status: str,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    decision = _require_decision(db, decision_id)
    require_family_feature(db, decision.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=decision.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if ctx is not None or x_dev_user:
        require_family_member(db, decision.family_id, actor.actor_id)
    if not decision_visible_to_actor(decision, actor_person_id=actor.actor_person_id, is_family_admin=actor.is_family_admin):
        raise HTTPException(status_code=403, detail="decision is not editable by this actor")

    previous_status = decision.status.value
    allowed = {item.value: item for item in DecisionStatusEnum}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="invalid status")
    before_state = _decision_state(decision)
    decision.status = allowed[status]
    decision.updated_at = utc_now()
    if status == DecisionStatusEnum.done.value:
        decision.completed_at = utc_now()
    db.commit()

    canonical_event_type = "decision.updated"
    legacy_event_type = "decision_status_updated"
    if status == DecisionStatusEnum.discretionary_approved.value:
        canonical_event_type = "decision.approved"
        legacy_event_type = "decision_approved"
    elif status == DecisionStatusEnum.rejected.value:
        canonical_event_type = "decision.rejected"
        legacy_event_type = "decision_rejected"
    elif status == DecisionStatusEnum.done.value:
        canonical_event_type = "decision.completed"
        legacy_event_type = "decision_completed"
    try:
        _emit_decision_event(
            decision=decision,
            actor_id=actor.actor_id,
            actor_person_id=actor.actor_person_id,
            event_type=canonical_event_type,
            payload=_decision_payload(
                decision,
                changed_fields=diff_field_paths(before_state, _decision_state(decision)),
                extra_payload={"previous_status": previous_status},
            ),
        )
    except Exception:
        logger.exception("Failed to emit %s for decision_id=%s", canonical_event_type, decision.id)
    record_agent_event(
        db,
        family_id=decision.family_id,
        domain="decision",
        source_agent="decision-api.decisions",
        actor=actor.actor_id,
        event_type=legacy_event_type,
        summary=f"Decision status changed: {decision.title} -> {status}",
        topic=decision.title,
        status=status,
        payload={"decision_id": decision.id, "previous_status": previous_status},
        emit_canonical=False,
    )
    db.commit()
    return {"decision_id": decision_id, "status": decision.status.value}
