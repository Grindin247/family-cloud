import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.models.entities import FamilyMember, Goal
from app.schemas.goals import GoalCreate, GoalListResponse, GoalResponse, GoalUpdate
from app.services.access import require_family_editor, require_family_feature, require_family_member
from app.services.ops import record_agent_event

router = APIRouter(prefix="/v1/goals", tags=["goals"])


def _to_goal_response(goal: Goal) -> GoalResponse:
    return GoalResponse(
        id=goal.id,
        family_id=goal.family_id,
        name=goal.name,
        description=goal.description,
        weight=goal.weight,
        action_types=json.loads(goal.action_types or "[]"),
        active=goal.active,
    )


@router.get("", response_model=GoalListResponse)
def list_goals(
    family_id: int | None = Query(default=None),
    active_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    query = select(Goal)
    if ctx is not None:
        query = query.join(FamilyMember, FamilyMember.family_id == Goal.family_id).where(FamilyMember.email == ctx.email)
    if family_id is not None:
        require_family_feature(db, family_id, "decision")
        if ctx is not None:
            require_family_member(db, family_id, ctx.email)
        query = query.where(Goal.family_id == family_id)
    if active_only:
        query = query.where(Goal.active.is_(True))
    goals = db.execute(query.order_by(Goal.id.asc())).scalars().all()
    return GoalListResponse(items=[_to_goal_response(goal) for goal in goals])


@router.get("/{goal_id}", response_model=GoalResponse)
def get_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="goal not found")
    if ctx is not None:
        require_family_member(db, goal.family_id, ctx.email)
    return _to_goal_response(goal)


@router.post("", response_model=GoalResponse, status_code=201)
def create_goal(
    payload: GoalCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    if ctx is not None:
        require_family_feature(db, payload.family_id, "decision")
        require_family_editor(db, payload.family_id, ctx.email)
    goal = Goal(
        family_id=payload.family_id,
        name=payload.name,
        description=payload.description,
        weight=payload.weight,
        action_types=json.dumps(payload.action_types),
        active=payload.active,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    record_agent_event(
        db,
        family_id=goal.family_id,
        domain="decision",
        source_agent="decision-api.goals",
        actor=ctx.email if ctx is not None else "system",
        event_type="goal_created",
        summary=f"Goal created: {goal.name}",
        topic=goal.name,
        status="active" if goal.active else "inactive",
        payload={"goal_id": goal.id, "weight": goal.weight},
    )
    db.commit()
    return _to_goal_response(goal)


@router.patch("/{goal_id}", response_model=GoalResponse)
def update_goal(
    goal_id: int,
    payload: GoalUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="goal not found")
    if ctx is not None:
        require_family_feature(db, goal.family_id, "decision")
        require_family_editor(db, goal.family_id, ctx.email)

    if payload.name is not None:
        goal.name = payload.name
    if payload.description is not None:
        goal.description = payload.description
    if payload.weight is not None:
        goal.weight = payload.weight
    if payload.action_types is not None:
        goal.action_types = json.dumps(payload.action_types)
    if payload.active is not None:
        goal.active = payload.active

    db.commit()
    db.refresh(goal)
    record_agent_event(
        db,
        family_id=goal.family_id,
        domain="decision",
        source_agent="decision-api.goals",
        actor=ctx.email if ctx is not None else "system",
        event_type="goal_updated",
        summary=f"Goal updated: {goal.name}",
        topic=goal.name,
        status="active" if goal.active else "inactive",
        payload={"goal_id": goal.id, "weight": goal.weight},
    )
    db.commit()
    return _to_goal_response(goal)


@router.delete("/{goal_id}", status_code=204)
def delete_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="goal not found")
    if ctx is not None:
        require_family_feature(db, goal.family_id, "decision")
        require_family_editor(db, goal.family_id, ctx.email)
    record_agent_event(
        db,
        family_id=goal.family_id,
        domain="decision",
        source_agent="decision-api.goals",
        actor=ctx.email if ctx is not None else "system",
        event_type="goal_deleted",
        summary=f"Goal deleted: {goal.name}",
        topic=goal.name,
        status="deleted",
        payload={"goal_id": goal.id},
    )
    db.delete(goal)
    db.commit()
