from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import (
    BudgetPolicy,
    Decision,
    DecisionQueueItem,
    DecisionScoreComponent,
    DecisionScoreRun,
    DiscretionaryBudgetLedger,
    Family,
    FamilyMember,
    Goal,
    MemberBudgetSetting,
    Period,
    RoadmapItem,
)
from app.models.identity import FamilyFeature, Person, PersonAccount, PersonAlias


def purge_family(db: Session, family_id: int) -> None:
    decision_ids = [row[0] for row in db.execute(select(Decision.id).where(Decision.family_id == family_id)).all()]
    goal_ids = [row[0] for row in db.execute(select(Goal.id).where(Goal.family_id == family_id)).all()]
    period_ids = [row[0] for row in db.execute(select(Period.id).where(Period.family_id == family_id)).all()]
    person_ids = [row[0] for row in db.execute(select(Person.person_id).where(Person.family_id == family_id)).all()]

    if decision_ids:
        db.execute(delete(DecisionScoreComponent).where(DecisionScoreComponent.decision_id.in_(decision_ids)))
        db.execute(delete(DecisionScoreRun).where(DecisionScoreRun.decision_id.in_(decision_ids)))
        db.execute(delete(DecisionQueueItem).where(DecisionQueueItem.decision_id.in_(decision_ids)))
        db.execute(delete(RoadmapItem).where(RoadmapItem.decision_id.in_(decision_ids)))

    if goal_ids:
        db.execute(delete(DecisionScoreComponent).where(DecisionScoreComponent.goal_id.in_(goal_ids)))

    if person_ids:
        db.execute(delete(MemberBudgetSetting).where(MemberBudgetSetting.person_id.in_(person_ids)))
        db.execute(delete(DiscretionaryBudgetLedger).where(DiscretionaryBudgetLedger.person_id.in_(person_ids)))
        db.execute(delete(PersonAccount).where(PersonAccount.person_id.in_(person_ids)))
        db.execute(delete(PersonAlias).where(PersonAlias.person_id.in_(person_ids)))
        db.execute(delete(Person).where(Person.person_id.in_(person_ids)))

    if period_ids:
        db.execute(delete(DiscretionaryBudgetLedger).where(DiscretionaryBudgetLedger.period_id.in_(period_ids)))

    db.execute(delete(FamilyFeature).where(FamilyFeature.family_id == family_id))
    db.execute(delete(BudgetPolicy).where(BudgetPolicy.family_id == family_id))
    db.execute(delete(Period).where(Period.family_id == family_id))
    db.execute(delete(Goal).where(Goal.family_id == family_id))
    db.execute(delete(Decision).where(Decision.family_id == family_id))
    db.execute(delete(FamilyMember).where(FamilyMember.family_id == family_id))
    db.execute(delete(Family).where(Family.id == family_id))
