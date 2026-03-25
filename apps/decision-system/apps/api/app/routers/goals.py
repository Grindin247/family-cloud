from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.models.entities import Goal, GoalStatusEnum, ScopeTypeEnum, VisibilityScopeEnum
from app.schemas.goals import GoalCreate, GoalListResponse, GoalResponse, GoalUpdate
from app.services.access import require_family_editor, require_family_feature
from app.services.decision_domain import (
    goal_visible_to_actor,
    normalize_visibility,
    parse_person_id,
    resolve_actor_access_context,
    utc_now,
    validate_scoped_owner,
)
from app.services.family_events import make_backend_event_payload
from app.services.ops import record_agent_event
from agents.common.family_events import diff_field_paths, make_privacy, publish_event as publish_family_event, snippet_fields

router = APIRouter(prefix="/v1/goals", tags=["goals"])
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


def _goal_state(goal: Goal) -> dict:
    return {
        "scope_type": goal.scope_type.value,
        "owner_person_id": str(goal.owner_person_id) if goal.owner_person_id is not None else None,
        "visibility_scope": goal.visibility_scope.value,
        "name": goal.name,
        "description": goal.description,
        "weight": goal.weight,
        "action_types": list(goal.action_types_json or []),
        "status": goal.status.value,
        "priority": goal.priority,
        "horizon": goal.horizon,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "success_criteria": goal.success_criteria,
        "review_cadence_days": goal.review_cadence_days,
        "next_review_at": goal.next_review_at.isoformat() if goal.next_review_at else None,
        "tags": list(goal.tags_json or []),
        "external_refs": list(goal.external_refs_json or []),
        "goal_revision": goal.goal_revision,
        "deleted_at": goal.deleted_at.isoformat() if goal.deleted_at else None,
    }


def _goal_payload(goal: Goal, *, changed_fields: list[str] | None = None, extra_payload: dict | None = None) -> dict:
    payload = {
        "goal_id": goal.id,
        "scope_type": goal.scope_type.value,
        "owner_person_id": str(goal.owner_person_id) if goal.owner_person_id is not None else None,
        "visibility_scope": goal.visibility_scope.value,
        "status": goal.status.value,
        "weight": goal.weight,
        "priority": goal.priority,
        "horizon": goal.horizon,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "review_cadence_days": goal.review_cadence_days,
        "next_review_at": goal.next_review_at.isoformat() if goal.next_review_at else None,
        "goal_revision": goal.goal_revision,
        "action_types": list(goal.action_types_json or []),
        "action_type_count": len(goal.action_types_json or []),
        "tags": list(goal.tags_json or []),
        "tag_count": len(goal.tags_json or []),
        "external_ref_count": len(goal.external_refs_json or []),
    }
    if changed_fields:
        payload["changed_fields"] = changed_fields
    if extra_payload:
        payload.update({key: value for key, value in extra_payload.items() if value is not None})
    payload.update(snippet_fields("name", goal.name))
    payload.update(snippet_fields("description", goal.description))
    payload.update(snippet_fields("success_criteria", goal.success_criteria))
    payload["title"] = payload.get("name_snippet") or f"Goal {goal.id}"
    return payload


def _emit_goal_event(*, goal: Goal, actor_id: str, actor_person_id: str | None, event_type: str, payload: dict) -> None:
    event = make_backend_event_payload(
        family_id=goal.family_id,
        domain="decision",
        event_type=event_type,
        actor_id=actor_id,
        actor_type="user",
        actor_person_id=actor_person_id,
        subject_id=str(goal.id),
        subject_type="goal",
        subject_person_id=str(goal.owner_person_id) if goal.owner_person_id is not None else None,
        payload=payload,
        source_agent_id="DecisionAgent",
        source_runtime="backend",
        tags=list(goal.tags_json or []),
        privacy=make_privacy(
            contains_pii=bool(goal.owner_person_id),
            contains_child_data=bool(goal.owner_person_id),
            contains_free_text=any(key.endswith("_snippet") for key in payload),
        ),
    )
    publish_family_event(event)


def _require_goal(db: Session, goal_id: int) -> Goal:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="goal not found")
    return goal


@router.get("", response_model=GoalListResponse)
def list_goals(
    family_id: int = Query(...),
    scope_type: ScopeTypeEnum | None = Query(default=None),
    owner_person_id: str | None = Query(default=None),
    visibility_scope: VisibilityScopeEnum | None = Query(default=None),
    status: GoalStatusEnum | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family_feature(db, family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user)

    query = select(Goal).where(Goal.family_id == family_id)
    if scope_type is not None:
        query = query.where(Goal.scope_type == scope_type)
    if owner_person_id is not None:
        query = query.where(Goal.owner_person_id == parse_person_id(owner_person_id))
    if visibility_scope is not None:
        query = query.where(Goal.visibility_scope == visibility_scope)
    if status is not None:
        query = query.where(Goal.status == status)
    if not include_deleted:
        query = query.where(Goal.deleted_at.is_(None))
    goals = db.execute(query.order_by(Goal.scope_type.asc(), Goal.priority.desc().nullslast(), Goal.id.asc())).scalars().all()
    visible = [
        _serialize_goal(goal)
        for goal in goals
        if goal_visible_to_actor(
            goal,
            actor_person_id=actor.actor_person_id,
            is_family_admin=actor.is_family_admin,
            include_deleted=include_deleted,
        )
    ]
    return GoalListResponse(items=visible)


@router.get("/{goal_id}", response_model=GoalResponse)
def get_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    goal = _require_goal(db, goal_id)
    require_family_feature(db, goal.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=goal.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if not goal_visible_to_actor(goal, actor_person_id=actor.actor_person_id, is_family_admin=actor.is_family_admin):
        raise HTTPException(status_code=403, detail="goal is not visible to this actor")
    return _serialize_goal(goal)


@router.post("", response_model=GoalResponse, status_code=201)
def create_goal(
    payload: GoalCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family_feature(db, payload.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=payload.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if ctx is not None or x_dev_user:
        require_family_editor(db, payload.family_id, actor.actor_id)

    owner = validate_scoped_owner(
        db,
        family_id=payload.family_id,
        scope_type=payload.scope_type,
        owner_person_id=payload.owner_person_id,
    )
    if payload.scope_type == ScopeTypeEnum.person and not actor.is_family_admin and actor.actor_person_id != str(owner.person_id if owner else ""):
        raise HTTPException(status_code=403, detail="personal goals can only be created for yourself unless you are a family admin")

    now = utc_now()
    goal = Goal(
        family_id=payload.family_id,
        scope_type=payload.scope_type,
        owner_person_id=owner.person_id if owner is not None else None,
        visibility_scope=normalize_visibility(payload.scope_type, payload.visibility_scope),
        name=payload.name,
        description=payload.description,
        weight=payload.weight,
        action_types_json=payload.action_types,
        status=payload.status,
        priority=payload.priority,
        horizon=payload.horizon,
        target_date=payload.target_date,
        success_criteria=payload.success_criteria,
        review_cadence_days=payload.review_cadence_days,
        next_review_at=payload.next_review_at,
        tags_json=payload.tags,
        external_refs_json=payload.external_refs,
        goal_revision=1,
        created_at=now,
        updated_at=now,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    try:
        _emit_goal_event(
            goal=goal,
            actor_id=actor.actor_id,
            actor_person_id=actor.actor_person_id,
            event_type="goal.created",
            payload=_goal_payload(goal),
        )
    except Exception:
        logger.exception("Failed to emit goal.created for goal_id=%s", goal.id)
    record_agent_event(
        db,
        family_id=goal.family_id,
        domain="decision",
        source_agent="decision-api.goals",
        actor=actor.actor_id,
        event_type="goal_created",
        summary=f"Goal created: {goal.name}",
        topic=goal.name,
        status=goal.status.value,
        payload={
            "goal_id": goal.id,
            "scope_type": goal.scope_type.value,
            "owner_person_id": str(goal.owner_person_id) if goal.owner_person_id is not None else None,
        },
        emit_canonical=False,
    )
    db.commit()
    return _serialize_goal(goal)


@router.patch("/{goal_id}", response_model=GoalResponse)
def update_goal(
    goal_id: int,
    payload: GoalUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    goal = _require_goal(db, goal_id)
    require_family_feature(db, goal.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=goal.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if ctx is not None or x_dev_user:
        require_family_editor(db, goal.family_id, actor.actor_id)
    if not goal_visible_to_actor(goal, actor_person_id=actor.actor_person_id, is_family_admin=actor.is_family_admin):
        raise HTTPException(status_code=403, detail="goal is not editable by this actor")

    next_scope = payload.scope_type or goal.scope_type
    next_owner_person_id = payload.owner_person_id if payload.owner_person_id is not None else (str(goal.owner_person_id) if goal.owner_person_id is not None else None)
    owner = validate_scoped_owner(
        db,
        family_id=goal.family_id,
        scope_type=next_scope,
        owner_person_id=next_owner_person_id,
    )
    if next_scope == ScopeTypeEnum.person and not actor.is_family_admin and actor.actor_person_id != str(owner.person_id if owner else ""):
        raise HTTPException(status_code=403, detail="personal goals can only be reassigned to yourself unless you are a family admin")

    before_state = _goal_state(goal)
    changed = False
    next_owner = owner.person_id if owner is not None else None
    requested_visibility = payload.visibility_scope if payload.visibility_scope is not None else (None if payload.scope_type is not None else goal.visibility_scope)
    next_visibility = normalize_visibility(next_scope, requested_visibility)
    if next_scope != goal.scope_type:
        goal.scope_type = next_scope
        changed = True
    if goal.owner_person_id != next_owner:
        goal.owner_person_id = next_owner
        changed = True
    if goal.visibility_scope != next_visibility:
        goal.visibility_scope = next_visibility
        changed = True
    for field in ("name", "description", "weight", "status", "priority", "horizon", "target_date", "success_criteria", "review_cadence_days", "next_review_at"):
        value = getattr(payload, field)
        if value is not None and getattr(goal, field) != value:
            setattr(goal, field, value)
            changed = True
    if payload.action_types is not None and goal.action_types_json != payload.action_types:
        goal.action_types_json = payload.action_types
        changed = True
    if payload.tags is not None and goal.tags_json != payload.tags:
        goal.tags_json = payload.tags
        changed = True
    if payload.external_refs is not None and goal.external_refs_json != payload.external_refs:
        goal.external_refs_json = payload.external_refs
        changed = True

    if changed:
        goal.goal_revision += 1
    goal.updated_at = utc_now()

    db.commit()
    db.refresh(goal)
    try:
        _emit_goal_event(
            goal=goal,
            actor_id=actor.actor_id,
            actor_person_id=actor.actor_person_id,
            event_type="goal.updated",
            payload=_goal_payload(goal, changed_fields=diff_field_paths(before_state, _goal_state(goal))),
        )
    except Exception:
        logger.exception("Failed to emit goal.updated for goal_id=%s", goal.id)
    record_agent_event(
        db,
        family_id=goal.family_id,
        domain="decision",
        source_agent="decision-api.goals",
        actor=actor.actor_id,
        event_type="goal_updated",
        summary=f"Goal updated: {goal.name}",
        topic=goal.name,
        status=goal.status.value,
        payload={"goal_id": goal.id, "goal_revision": goal.goal_revision},
        emit_canonical=False,
    )
    db.commit()
    return _serialize_goal(goal)


@router.delete("/{goal_id}", status_code=204)
def delete_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    goal = _require_goal(db, goal_id)
    require_family_feature(db, goal.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=goal.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if ctx is not None or x_dev_user:
        require_family_editor(db, goal.family_id, actor.actor_id)
    if not goal_visible_to_actor(goal, actor_person_id=actor.actor_person_id, is_family_admin=actor.is_family_admin):
        raise HTTPException(status_code=403, detail="goal is not deletable by this actor")

    goal.deleted_at = utc_now()
    goal.updated_at = goal.deleted_at
    goal.status = GoalStatusEnum.archived
    goal.goal_revision += 1
    db.commit()
    try:
        _emit_goal_event(
            goal=goal,
            actor_id=actor.actor_id,
            actor_person_id=actor.actor_person_id,
            event_type="goal.deleted",
            payload=_goal_payload(goal, changed_fields=["status", "deleted_at", "updated_at", "goal_revision"]),
        )
    except Exception:
        logger.exception("Failed to emit goal.deleted for goal_id=%s", goal.id)
    record_agent_event(
        db,
        family_id=goal.family_id,
        domain="decision",
        source_agent="decision-api.goals",
        actor=actor.actor_id,
        event_type="goal_deleted",
        summary=f"Goal deleted: {goal.name}",
        topic=goal.name,
        status="deleted",
        payload={"goal_id": goal.id},
        emit_canonical=False,
    )
    db.commit()
