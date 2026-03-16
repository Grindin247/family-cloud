from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import (
    BudgetPolicy,
    Decision,
    DecisionQueueItem,
    DecisionScore,
    DiscretionaryBudgetLedger,
    Family,
    FamilyMember,
    Goal,
    MemberBudgetSetting,
    Period,
    RoadmapItem,
)


def purge_family(db: Session, family_id: int) -> None:
    """
    Hard-delete a family and all dependent records.

    We do this explicitly (instead of relying on ON DELETE CASCADE) so existing
    installations can purge data without a migration to rewrite FK constraints.
    """
    member_ids = [
        row[0]
        for row in db.execute(select(FamilyMember.id).where(FamilyMember.family_id == family_id)).all()
    ]
    decision_ids = [
        row[0] for row in db.execute(select(Decision.id).where(Decision.family_id == family_id)).all()
    ]
    goal_ids = [row[0] for row in db.execute(select(Goal.id).where(Goal.family_id == family_id)).all()]
    period_ids = [
        row[0] for row in db.execute(select(Period.id).where(Period.family_id == family_id)).all()
    ]

    # Decision children
    if decision_ids:
        db.execute(delete(DecisionScore).where(DecisionScore.decision_id.in_(decision_ids)))
        db.execute(delete(DecisionQueueItem).where(DecisionQueueItem.decision_id.in_(decision_ids)))
        db.execute(delete(RoadmapItem).where(RoadmapItem.decision_id.in_(decision_ids)))

    # Goal children
    if goal_ids:
        db.execute(delete(DecisionScore).where(DecisionScore.goal_id.in_(goal_ids)))

    # Budget/period/member children
    if member_ids:
        db.execute(delete(MemberBudgetSetting).where(MemberBudgetSetting.member_id.in_(member_ids)))
        db.execute(delete(DiscretionaryBudgetLedger).where(DiscretionaryBudgetLedger.member_id.in_(member_ids)))

    if period_ids:
        db.execute(delete(DiscretionaryBudgetLedger).where(DiscretionaryBudgetLedger.period_id.in_(period_ids)))

    # Family-scoped tables
    db.execute(delete(BudgetPolicy).where(BudgetPolicy.family_id == family_id))
    db.execute(delete(Period).where(Period.family_id == family_id))
    db.execute(delete(Goal).where(Goal.family_id == family_id))
    db.execute(delete(Decision).where(Decision.family_id == family_id))
    db.execute(delete(FamilyMember).where(FamilyMember.family_id == family_id))
    db.execute(delete(Family).where(Family.id == family_id))

