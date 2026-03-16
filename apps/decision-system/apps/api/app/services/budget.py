from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    BudgetPolicy,
    DiscretionaryBudgetLedger,
    Family,
    FamilyMember,
    MemberBudgetSetting,
    Period,
    PeriodTypeEnum,
)

DEFAULT_THRESHOLD = 4.0
DEFAULT_PERIOD_DAYS = 90
DEFAULT_ALLOWANCE = 2


def _next_period_window(start_date: date, period_days: int) -> tuple[date, date]:
    return start_date, start_date + timedelta(days=period_days - 1)


def get_or_create_policy(db: Session, family_id: int) -> BudgetPolicy:
    policy = db.execute(select(BudgetPolicy).where(BudgetPolicy.family_id == family_id)).scalar_one_or_none()
    if policy is not None:
        return policy

    family = db.get(Family, family_id)
    if family is None:
        raise ValueError("family not found")

    policy = BudgetPolicy(
        family_id=family_id,
        threshold_1_to_5=DEFAULT_THRESHOLD,
        period_days=DEFAULT_PERIOD_DAYS,
        default_allowance=DEFAULT_ALLOWANCE,
    )
    db.add(policy)
    db.flush()
    return policy


def member_allowance_map(db: Session, family_id: int, default_allowance: int) -> dict[int, int]:
    members = db.execute(select(FamilyMember).where(FamilyMember.family_id == family_id)).scalars().all()
    overrides = db.execute(select(MemberBudgetSetting).where(MemberBudgetSetting.family_id == family_id)).scalars().all()
    override_map = {item.member_id: item.allowance for item in overrides}
    return {member.id: override_map.get(member.id, default_allowance) for member in members}


def _allocate_period_ledger(db: Session, family_id: int, period_id: int, allowances: dict[int, int]) -> None:
    for member_id, allowance in allowances.items():
        db.add(
            DiscretionaryBudgetLedger(
                member_id=member_id,
                period_id=period_id,
                delta=allowance,
                reason="period_allocation",
                decision_id=None,
            )
        )


def ensure_active_period(db: Session, family_id: int, today: date | None = None) -> Period:
    target_date = today or date.today()
    policy = get_or_create_policy(db, family_id)
    active_periods = db.execute(
        select(Period).where(
            Period.family_id == family_id,
            Period.start_date <= target_date,
            Period.end_date >= target_date,
        )
    ).scalars().all()
    if active_periods:
        # Repair historical overlaps by keeping the most recent active period.
        active_periods.sort(key=lambda item: (item.start_date, item.id), reverse=True)
        chosen = active_periods[0]
        for stale in active_periods[1:]:
            stale.end_date = min(stale.end_date, chosen.start_date - timedelta(days=1))
        return chosen

    start_date, end_date = _next_period_window(target_date, policy.period_days)
    period = Period(
        family_id=family_id,
        start_date=start_date,
        end_date=end_date,
        type=PeriodTypeEnum.custom,
    )
    db.add(period)
    db.flush()

    allowances = member_allowance_map(db, family_id, policy.default_allowance)
    _allocate_period_ledger(db, family_id, period.id, allowances)
    db.flush()
    return period


def ensure_member_allocation_in_period(db: Session, family_id: int, period: Period, member_id: int) -> None:
    existing = db.execute(
        select(DiscretionaryBudgetLedger).where(
            DiscretionaryBudgetLedger.member_id == member_id,
            DiscretionaryBudgetLedger.period_id == period.id,
            DiscretionaryBudgetLedger.reason == "period_allocation",
        )
    ).scalar_one_or_none()
    if existing is not None:
        return

    policy = get_or_create_policy(db, family_id)
    allowance = member_allowance_map(db, family_id, policy.default_allowance).get(member_id, policy.default_allowance)
    db.add(
        DiscretionaryBudgetLedger(
            member_id=member_id,
            period_id=period.id,
            delta=allowance,
            reason="period_allocation",
            decision_id=None,
        )
    )


def member_remaining_in_period(db: Session, period_id: int, member_id: int) -> tuple[int, int, int]:
    rows = db.execute(
        select(DiscretionaryBudgetLedger).where(
            DiscretionaryBudgetLedger.period_id == period_id,
            DiscretionaryBudgetLedger.member_id == member_id,
        )
    ).scalars().all()

    allowance = sum(item.delta for item in rows if item.reason in {"period_allocation", "policy_adjustment"})
    spent_overrides = -sum(item.delta for item in rows if item.reason == "discretionary_schedule_override")
    spent_refunds = sum(item.delta for item in rows if item.reason == "discretionary_unschedule_refund")
    spent = max(spent_overrides - spent_refunds, 0)
    remaining = allowance - spent
    return allowance, spent, remaining
