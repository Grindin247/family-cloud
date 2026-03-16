from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.models.entities import BudgetPolicy, DiscretionaryBudgetLedger, Family, FamilyMember, MemberBudgetSetting, Period
from app.schemas.budgets import BudgetPolicyUpdate, BudgetSummaryResponse, MemberBudgetSummary
from app.services.budget import (
    ensure_active_period,
    ensure_member_allocation_in_period,
    get_or_create_policy,
    member_allowance_map,
    member_remaining_in_period,
)
from app.services.access import require_family_admin, require_family_editor, require_family_member

router = APIRouter(prefix="/v1/budgets", tags=["budgets"])


def _family_members(db: Session, family_id: int) -> list[FamilyMember]:
    return db.execute(select(FamilyMember).where(FamilyMember.family_id == family_id)).scalars().all()


def _summary_response(db: Session, family_id: int, period: Period, policy: BudgetPolicy) -> BudgetSummaryResponse:
    members = _family_members(db, family_id)
    summaries: list[MemberBudgetSummary] = []
    for member in members:
        ensure_member_allocation_in_period(db, family_id, period, member.id)
        allowance, used, remaining = member_remaining_in_period(db, period.id, member.id)
        summaries.append(
            MemberBudgetSummary(
                member_id=member.id,
                display_name=member.display_name,
                role=member.role.value,
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


@router.get("/families/{family_id}", response_model=BudgetSummaryResponse)
def get_budget_summary(
    family_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    family = db.get(Family, family_id)
    if family is None:
        raise HTTPException(status_code=404, detail="family not found")
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
    if ctx is not None:
        require_family_editor(db, family_id, ctx.email)

    members = _family_members(db, family_id)
    member_ids = {member.id for member in members}
    for item in payload.member_allowances:
        if item.member_id not in member_ids:
            raise HTTPException(status_code=400, detail=f"member {item.member_id} does not belong to family")

    policy = get_or_create_policy(db, family_id)
    policy.threshold_1_to_5 = payload.threshold_1_to_5
    policy.period_days = payload.period_days
    policy.default_allowance = payload.default_allowance

    existing_settings = db.execute(
        select(MemberBudgetSetting).where(MemberBudgetSetting.family_id == family_id)
    ).scalars().all()
    existing_map = {item.member_id: item for item in existing_settings}
    payload_map = {item.member_id: item.allowance for item in payload.member_allowances}

    for member_id, allowance in payload_map.items():
        setting = existing_map.get(member_id)
        if setting is None:
            db.add(MemberBudgetSetting(family_id=family_id, member_id=member_id, allowance=allowance))
        else:
            setting.allowance = allowance

    for member_id, setting in existing_map.items():
        if member_id not in payload_map:
            db.delete(setting)

    db.flush()
    period = ensure_active_period(db, family_id)
    allowances = member_allowance_map(db, family_id, policy.default_allowance)
    for member in members:
        ensure_member_allocation_in_period(db, family_id, period, member.id)
        current_allowance, _, _ = member_remaining_in_period(db, period.id, member.id)
        target_allowance = allowances.get(member.id, policy.default_allowance)
        delta = target_allowance - current_allowance
        if delta != 0:
            db.add(
                DiscretionaryBudgetLedger(
                    member_id=member.id,
                    period_id=period.id,
                    delta=delta,
                    reason="policy_adjustment",
                    decision_id=None,
                )
            )
    db.commit()
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
    if ctx is not None:
        require_family_admin(db, family_id, ctx.email)

    policy = get_or_create_policy(db, family_id)
    today = date.today()
    period = ensure_active_period(db, family_id, today=today)
    period.end_date = today - timedelta(days=1)

    new_period = ensure_active_period(db, family_id, today=today)
    db.commit()
    return _summary_response(db, family_id, new_period, policy)
