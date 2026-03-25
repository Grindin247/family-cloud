from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.models.entities import BudgetPolicy, DiscretionaryBudgetLedger, Family, MemberBudgetSetting
from app.models.identity import Person
from app.schemas.budgets import BudgetPolicyUpdate, BudgetSummaryResponse, PersonBudgetSummary
from app.services.access import require_family_admin, require_family_editor, require_family_feature, require_family_member
from app.services.budget import (
    ensure_active_period,
    ensure_person_allocation_in_period,
    get_or_create_policy,
    person_allowance_map,
    person_remaining_in_period,
)
from app.services.family_events import make_backend_event_payload
from app.services.identity import list_family_persons
from agents.common.family_events import make_privacy, publish_event as publish_family_event

router = APIRouter(prefix="/v1/budgets", tags=["budgets"])


def _family_persons(db: Session, family_id: int) -> list[Person]:
    return [person for person in list_family_persons(db, family_id) if person.status == "active"]


def _summary_response(db: Session, family_id: int, period, policy: BudgetPolicy) -> BudgetSummaryResponse:
    persons = _family_persons(db, family_id)
    summaries: list[PersonBudgetSummary] = []
    for person in persons:
        ensure_person_allocation_in_period(db, family_id, period, str(person.person_id))
        allowance, used, remaining = person_remaining_in_period(db, period.id, str(person.person_id))
        summaries.append(
            PersonBudgetSummary(
                person_id=str(person.person_id),
                display_name=person.display_name,
                role=person.role_in_family or "member",
                allowance=allowance,
                used=used,
                remaining=max(remaining, 0),
            )
        )

    return BudgetSummaryResponse(
        family_id=family_id,
        threshold_1_to_5=policy.threshold_1_to_5,
        period_days=policy.period_days,
        default_allowance=policy.default_allowance,
        period_start_date=period.start_date,
        period_end_date=period.end_date,
        members=summaries,
    )


def _actor_id(ctx: AuthContext | None) -> str:
    return ctx.email if ctx is not None else "system"


def _emit_budget_event(*, family_id: int, actor_id: str, event_type: str, payload: dict) -> None:
    event = make_backend_event_payload(
        family_id=family_id,
        domain="decision",
        event_type=event_type,
        actor_id=actor_id,
        actor_type="user" if actor_id != "system" else "system",
        subject_id=str(family_id),
        subject_type="budget",
        payload=payload,
        source_agent_id="DecisionAgent",
        source_runtime="backend",
        tags=["budget"],
        privacy=make_privacy(contains_financial_data=True),
    )
    publish_family_event(event)


@router.get("/families/{family_id}", response_model=BudgetSummaryResponse)
def get_budget_summary(
    family_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    family = db.get(Family, family_id)
    if family is None:
        raise HTTPException(status_code=404, detail="family not found")
    require_family_feature(db, family_id, "decision")
    if ctx is not None:
        require_family_member(db, family_id, ctx.email)

    policy = get_or_create_policy(db, family_id)
    period = ensure_active_period(db, family_id)
    db.commit()
    return _summary_response(db, family_id, period, policy)


@router.put("/families/{family_id}/policy", response_model=BudgetSummaryResponse)
def update_budget_policy(
    family_id: int,
    payload: BudgetPolicyUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    family = db.get(Family, family_id)
    if family is None:
        raise HTTPException(status_code=404, detail="family not found")
    require_family_feature(db, family_id, "decision")
    if ctx is not None:
        require_family_editor(db, family_id, ctx.email)

    persons = _family_persons(db, family_id)
    person_ids = {str(person.person_id) for person in persons}
    for item in payload.person_allowances:
        if item.person_id not in person_ids:
            raise HTTPException(status_code=400, detail=f"person {item.person_id} does not belong to family")

    policy = get_or_create_policy(db, family_id)
    before_policy = {
        "threshold_1_to_5": policy.threshold_1_to_5,
        "period_days": policy.period_days,
        "default_allowance": policy.default_allowance,
    }
    policy.threshold_1_to_5 = payload.threshold_1_to_5
    policy.period_days = payload.period_days
    policy.default_allowance = payload.default_allowance

    existing_settings = db.execute(select(MemberBudgetSetting).where(MemberBudgetSetting.family_id == family_id)).scalars().all()
    existing_map = {str(item.person_id): item for item in existing_settings}
    payload_map = {item.person_id: item.allowance for item in payload.person_allowances}

    for person_id, allowance in payload_map.items():
        setting = existing_map.get(person_id)
        if setting is None:
            db.add(MemberBudgetSetting(family_id=family_id, person_id=UUID(person_id), allowance=allowance))
        else:
            setting.allowance = allowance

    for person_id, setting in existing_map.items():
        if person_id not in payload_map:
            db.delete(setting)

    db.flush()
    period = ensure_active_period(db, family_id)
    allowances = person_allowance_map(db, family_id, policy.default_allowance)
    for person in persons:
        ensure_person_allocation_in_period(db, family_id, period, str(person.person_id))
        current_allowance, _, _ = person_remaining_in_period(db, period.id, str(person.person_id))
        target_allowance = allowances.get(str(person.person_id), policy.default_allowance)
        delta = target_allowance - current_allowance
        if delta != 0:
            db.add(
                DiscretionaryBudgetLedger(
                    person_id=person.person_id,
                    period_id=period.id,
                    delta=delta,
                    reason="policy_adjustment",
                    decision_id=None,
                )
            )
    db.commit()
    try:
        _emit_budget_event(
            family_id=family_id,
            actor_id=_actor_id(ctx),
            event_type="budget.policy.updated",
            payload={
                "title": "Budget policy updated",
                "threshold_1_to_5": policy.threshold_1_to_5,
                "period_days": policy.period_days,
                "default_allowance": policy.default_allowance,
                "member_allowance_count": len(payload.person_allowances),
                "changed_fields": [
                    field
                    for field, value in {
                        "threshold_1_to_5": policy.threshold_1_to_5,
                        "period_days": policy.period_days,
                        "default_allowance": policy.default_allowance,
                    }.items()
                    if before_policy.get(field) != value
                ],
            },
        )
    except Exception:
        pass
    return _summary_response(db, family_id, period, policy)


@router.post("/families/{family_id}/period/reset", response_model=BudgetSummaryResponse)
def reset_budget_period(
    family_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    family = db.get(Family, family_id)
    if family is None:
        raise HTTPException(status_code=404, detail="family not found")
    require_family_feature(db, family_id, "decision")
    if ctx is not None:
        require_family_admin(db, family_id, ctx.email)

    policy = get_or_create_policy(db, family_id)
    today = date.today()
    period = ensure_active_period(db, family_id, today=today)
    period.end_date = today - timedelta(days=1)

    new_period = ensure_active_period(db, family_id, today=today)
    db.commit()
    try:
        _emit_budget_event(
            family_id=family_id,
            actor_id=_actor_id(ctx),
            event_type="budget.period.reset",
            payload={
                "title": "Budget period reset",
                "period_start_date": new_period.start_date.isoformat(),
                "period_end_date": new_period.end_date.isoformat(),
                "threshold_1_to_5": policy.threshold_1_to_5,
                "default_allowance": policy.default_allowance,
            },
        )
    except Exception:
        pass
    return _summary_response(db, family_id, new_period, policy)
