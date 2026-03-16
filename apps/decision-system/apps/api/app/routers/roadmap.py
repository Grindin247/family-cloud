import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.models.entities import Decision, DecisionScore, DecisionStatusEnum, DiscretionaryBudgetLedger, FamilyMember, Goal, RoadmapItem
from app.schemas.roadmaps import RoadmapCreate, RoadmapListResponse, RoadmapResponse, RoadmapUpdate
from app.services.budget import (
    ensure_active_period,
    ensure_member_allocation_in_period,
    get_or_create_policy,
    member_remaining_in_period,
)
from app.services.scoring import GoalScoreInput, compute_weighted_score
from app.services.access import require_family_member
from app.services.event_bus import publish_event
from app.services.ops import record_agent_event
from agents.common.events.subjects import Subjects
from app.services.memory import create_document_with_embeddings

router = APIRouter(prefix="/v1/roadmap", tags=["roadmap"])


def _to_response(item: RoadmapItem) -> RoadmapResponse:
    return RoadmapResponse(
        id=item.id,
        decision_id=item.decision_id,
        bucket=item.bucket,
        start_date=item.start_date,
        end_date=item.end_date,
        status=item.status,
        dependencies=json.loads(item.dependencies or "[]"),
    )


def _decision_weighted_score(db: Session, decision: Decision) -> float | None:
    rows = db.execute(
        select(DecisionScore, Goal).join(Goal, Goal.id == DecisionScore.goal_id).where(
            DecisionScore.decision_id == decision.id,
            DecisionScore.version == decision.version,
        )
    ).all()
    if not rows:
        return None
    weighted = [GoalScoreInput(weight=goal.weight, score=score.score_1_to_5) for score, goal in rows]
    return compute_weighted_score(weighted, normalize_to=5)


@router.get("", response_model=RoadmapListResponse)
def list_roadmap_items(
    family_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    query = select(RoadmapItem)
    if ctx is not None:
        query = (
            query.join(Decision, Decision.id == RoadmapItem.decision_id)
            .join(FamilyMember, FamilyMember.family_id == Decision.family_id)
            .where(FamilyMember.email == ctx.email)
        )
    if family_id is not None:
        if ctx is not None:
            require_family_member(db, family_id, ctx.email)
        if ctx is None:
            query = query.join(Decision, Decision.id == RoadmapItem.decision_id)
        query = query.where(Decision.family_id == family_id)
    items = db.execute(query.order_by(RoadmapItem.id.desc())).scalars().all()
    return RoadmapListResponse(items=[_to_response(item) for item in items])


@router.post("", response_model=RoadmapResponse, status_code=201)
def create_roadmap_item(
    payload: RoadmapCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    decision = db.get(Decision, payload.decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="decision not found")
    if ctx is not None:
        require_family_member(db, decision.family_id, ctx.email)

    policy = get_or_create_policy(db, decision.family_id)
    weighted_score = _decision_weighted_score(db, decision)
    meets_threshold = weighted_score is not None and weighted_score >= policy.threshold_1_to_5

    if not meets_threshold:
        if not payload.use_discretionary_budget:
            raise HTTPException(
                status_code=400,
                detail=f"decision score must meet threshold ({policy.threshold_1_to_5}) or use discretionary budget",
            )

        period = ensure_active_period(db, decision.family_id)
        ensure_member_allocation_in_period(db, decision.family_id, period, decision.created_by_member_id)
        allowance, used, remaining = member_remaining_in_period(db, period.id, decision.created_by_member_id)
        if remaining < 1:
            raise HTTPException(
                status_code=400,
                detail=f"discretionary budget exhausted for member (used {used} of {allowance} this period)",
            )

        db.add(
            DiscretionaryBudgetLedger(
                member_id=decision.created_by_member_id,
                period_id=period.id,
                delta=-1,
                reason="discretionary_schedule_override",
                decision_id=decision.id,
            )
        )
        decision.status = DecisionStatusEnum.discretionary_approved

    item = RoadmapItem(
        decision_id=payload.decision_id,
        bucket=payload.bucket,
        start_date=payload.start_date,
        end_date=payload.end_date,
        status=payload.status,
        dependencies=json.dumps(payload.dependencies),
    )
    db.add(item)
    decision.status = DecisionStatusEnum.scheduled
    db.commit()
    db.refresh(item)
    try:
        create_document_with_embeddings(
            db,
            family_id=decision.family_id,
            type="roadmap",
            text_value=f"Roadmap item created: id={item.id} decision_id={item.decision_id} bucket={item.bucket} start={item.start_date} end={item.end_date} status={item.status}",
            source_refs=[],
        )
        db.commit()
    except Exception:
        db.rollback()
    try:
        publish_event(
            Subjects.ROADMAP_ITEM_ADDED,
            {"roadmap_item_id": item.id, "decision_id": item.decision_id},
            actor=ctx.email if ctx is not None else "system",
            family_id=decision.family_id,
            source="decision-api.roadmap",
        )
    except Exception:
        pass
    record_agent_event(
        db,
        family_id=decision.family_id,
        domain="decision",
        source_agent="decision-api.roadmap",
        actor=ctx.email if ctx is not None else "system",
        event_type="roadmap_item_created",
        summary=f"Roadmap item created for {decision.title}",
        topic=decision.title,
        status=item.status,
        payload={"roadmap_item_id": item.id, "decision_id": item.decision_id, "due_at": item.end_date},
    )
    db.commit()
    return _to_response(item)


@router.patch("/{roadmap_id}", response_model=RoadmapResponse)
def update_roadmap_item(
    roadmap_id: int,
    payload: RoadmapUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    item = db.get(RoadmapItem, roadmap_id)
    if item is None:
        raise HTTPException(status_code=404, detail="roadmap item not found")
    if ctx is not None:
        decision = db.get(Decision, item.decision_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="decision not found")
        require_family_member(db, decision.family_id, ctx.email)

    if payload.bucket is not None:
        item.bucket = payload.bucket
    if payload.start_date is not None:
        item.start_date = payload.start_date
    if payload.end_date is not None:
        item.end_date = payload.end_date
    if payload.status is not None:
        item.status = payload.status
    if payload.dependencies is not None:
        item.dependencies = json.dumps(payload.dependencies)

    db.commit()
    db.refresh(item)
    try:
        decision = db.get(Decision, item.decision_id)
        if decision is not None:
            create_document_with_embeddings(
                db,
                family_id=decision.family_id,
                type="roadmap",
                text_value=f"Roadmap item updated: id={item.id} decision_id={item.decision_id} bucket={item.bucket} start={item.start_date} end={item.end_date} status={item.status}",
                source_refs=[],
            )
            db.commit()
    except Exception:
        db.rollback()
    try:
        decision = db.get(Decision, item.decision_id)
        if decision is not None:
            publish_event(
                Subjects.ROADMAP_ITEM_UPDATED,
                {"roadmap_item_id": item.id, "decision_id": item.decision_id},
                actor=ctx.email if ctx is not None else "system",
                family_id=decision.family_id,
                source="decision-api.roadmap",
            )
    except Exception:
        pass
    if decision is not None:
        record_agent_event(
            db,
            family_id=decision.family_id,
            domain="decision",
            source_agent="decision-api.roadmap",
            actor=ctx.email if ctx is not None else "system",
            event_type="roadmap_item_updated",
            summary=f"Roadmap item updated for {decision.title}",
            topic=decision.title,
            status=item.status,
            payload={"roadmap_item_id": item.id, "decision_id": item.decision_id, "due_at": item.end_date},
        )
        db.commit()
    return _to_response(item)


@router.delete("/{roadmap_id}", status_code=204)
def delete_roadmap_item(
    roadmap_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    item = db.get(RoadmapItem, roadmap_id)
    if item is None:
        raise HTTPException(status_code=404, detail="roadmap item not found")
    decision = db.get(Decision, item.decision_id)
    if ctx is not None:
        if decision is None:
            raise HTTPException(status_code=404, detail="decision not found")
        require_family_member(db, decision.family_id, ctx.email)

    if item.status != "Done":
        debits = db.execute(
            select(DiscretionaryBudgetLedger).where(
                DiscretionaryBudgetLedger.decision_id == item.decision_id,
                DiscretionaryBudgetLedger.reason == "discretionary_schedule_override",
            )
        ).scalars().all()
        refunds = db.execute(
            select(DiscretionaryBudgetLedger).where(
                DiscretionaryBudgetLedger.decision_id == item.decision_id,
                DiscretionaryBudgetLedger.reason == "discretionary_unschedule_refund",
            )
        ).scalars().all()

        if len(debits) > len(refunds):
            latest_debit = sorted(debits, key=lambda row: row.id, reverse=True)[0]
            db.add(
                DiscretionaryBudgetLedger(
                    member_id=latest_debit.member_id,
                    period_id=latest_debit.period_id,
                    delta=1,
                    reason="discretionary_unschedule_refund",
                    decision_id=item.decision_id,
                )
            )
    if decision is not None:
        record_agent_event(
            db,
            family_id=decision.family_id,
            domain="decision",
            source_agent="decision-api.roadmap",
            actor=ctx.email if ctx is not None else "system",
            event_type="roadmap_item_deleted",
            summary=f"Roadmap item deleted for {decision.title}",
            topic=decision.title,
            status=item.status,
            payload={"roadmap_item_id": item.id, "decision_id": item.decision_id},
        )
    db.delete(item)
    db.commit()
