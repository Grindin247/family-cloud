from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthContext
from app.models.entities import (
    Decision,
    Goal,
    GoalPolicyEnum,
    GoalStatusEnum,
    ScopeTypeEnum,
    VisibilityScopeEnum,
)
from app.models.identity import Person
from app.services.access import require_person


@dataclass
class ActorAccessContext:
    actor_id: str
    actor_person_id: str | None
    is_family_admin: bool


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_actor_access_context(
    db: Session,
    *,
    family_id: int,
    ctx: AuthContext | None,
    x_dev_user: str | None = None,
) -> ActorAccessContext:
    from app.services.access import require_family_person

    actor_id = ctx.email if ctx is not None else (x_dev_user.strip().lower() if x_dev_user else "system")
    if ctx is None and not x_dev_user:
        return ActorAccessContext(actor_id=actor_id, actor_person_id=None, is_family_admin=True)
    person = require_family_person(db, family_id, actor_id)
    return ActorAccessContext(
        actor_id=actor_id,
        actor_person_id=str(person.person_id),
        is_family_admin=bool(person.is_admin),
    )


def normalize_visibility(scope_type: ScopeTypeEnum, visibility_scope: VisibilityScopeEnum | None) -> VisibilityScopeEnum:
    if visibility_scope is not None:
        return visibility_scope
    if scope_type == ScopeTypeEnum.person:
        return VisibilityScopeEnum.personal
    return VisibilityScopeEnum.family


def normalize_goal_policy(scope_type: ScopeTypeEnum, goal_policy: GoalPolicyEnum | None) -> GoalPolicyEnum:
    if goal_policy is not None:
        return goal_policy
    if scope_type == ScopeTypeEnum.person:
        return GoalPolicyEnum.family_plus_person
    return GoalPolicyEnum.family_only


def validate_scoped_owner(
    db: Session,
    *,
    family_id: int,
    scope_type: ScopeTypeEnum,
    owner_person_id: str | None,
    field_name: str = "owner_person_id",
    required_for_person_scope: bool = True,
) -> Person | None:
    if scope_type == ScopeTypeEnum.person and required_for_person_scope and not owner_person_id:
        raise HTTPException(status_code=400, detail=f"{field_name} is required for person scope")
    if owner_person_id is None:
        return None
    return require_person(db, family_id, owner_person_id, field_name=field_name)


def validate_target_person(
    db: Session,
    *,
    family_id: int,
    target_person_id: str | None,
) -> Person | None:
    if target_person_id is None:
        return None
    return require_person(db, family_id, target_person_id, field_name="target_person_id")


def ensure_person_decision_shape(
    *,
    scope_type: ScopeTypeEnum,
    target_person_id: str | None,
    goal_policy: GoalPolicyEnum,
) -> None:
    if scope_type == ScopeTypeEnum.person and target_person_id is None:
        raise HTTPException(status_code=400, detail="target_person_id is required for person-scoped decisions")
    if scope_type == ScopeTypeEnum.family and goal_policy == GoalPolicyEnum.family_plus_person and target_person_id is None:
        raise HTTPException(status_code=400, detail="target_person_id is required when goal_policy is family_plus_person")


def goal_visible_to_actor(
    goal: Goal,
    *,
    actor_person_id: str | None,
    is_family_admin: bool,
    include_deleted: bool = False,
) -> bool:
    if goal.deleted_at is not None and not include_deleted:
        return False
    if goal.visibility_scope == VisibilityScopeEnum.family:
        return True
    if is_family_admin:
        return True
    if actor_person_id is None:
        return True
    return str(goal.owner_person_id) == actor_person_id


def decision_visible_to_actor(
    decision: Decision,
    *,
    actor_person_id: str | None,
    is_family_admin: bool,
    include_deleted: bool = False,
) -> bool:
    if decision.deleted_at is not None and not include_deleted:
        return False
    if decision.visibility_scope == VisibilityScopeEnum.family:
        return True
    if is_family_admin:
        return True
    if actor_person_id is None:
        return True
    candidates = {
        str(value)
        for value in (decision.created_by_person_id, decision.owner_person_id, decision.target_person_id)
        if value is not None
    }
    return actor_person_id in candidates


def active_goal_for_scoring(goal: Goal) -> bool:
    return goal.deleted_at is None and goal.status == GoalStatusEnum.active


def persons_by_id(db: Session, family_id: int) -> dict[str, Person]:
    return {
        str(person.person_id): person
        for person in db.execute(select(Person).where(Person.family_id == family_id)).scalars().all()
    }


def parse_person_id(value: str | None) -> UUID | None:
    if value is None:
        return None
    return UUID(str(value))
