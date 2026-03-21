from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.models.entities import Decision, DecisionScoreRun, DecisionStatusEnum, DiscretionaryBudgetLedger, RoadmapItem
from app.schemas.roadmaps import RoadmapCreate, RoadmapListResponse, RoadmapResponse, RoadmapUpdate
from app.services.access import require_family_feature, require_family_member
from app.services.budget import (
    ensure_active_period,
    ensure_person_allocation_in_period,
    get_or_create_policy,
    person_remaining_in_period,
)
from app.services.decision_domain import decision_visible_to_actor, resolve_actor_access_context, utc_now
from app.services.event_bus import publish_event
from app.services.memory import create_document_with_embeddings
from app.services.ops import record_agent_event
from agents.common.events.subjects import Subjects

router = APIRouter(prefix="/v1/roadmap", tags=["roadmap"])


def _serialize(item: RoadmapItem) -> RoadmapResponse:
    return RoadmapResponse(
        id=item.id,
        decision_id=item.decision_id,
        bucket=item.bucket,
        start_date=item.start_date,
        end_date=item.end_date,
        status=item.status,
        dependencies=list(item.dependencies_json or []),
    )


def _latest_score_run(db: Session, decision_id: int) -> DecisionScoreRun | None:
    return db.execute(
        select(DecisionScoreRun)
        .where(DecisionScoreRun.decision_id == decision_id)
        .order_by(DecisionScoreRun.created_at.desc(), DecisionScoreRun.id.desc())
    ).scalar_one_or_none()


def _budget_person_id(decision: Decision) -> str:
    return str(decision.owner_person_id or decision.target_person_id or decision.created_by_person_id)


@router.get("", response_model=RoadmapListResponse)
def list_roadmap_items(
    family_id: int = Query(...),
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family_feature(db, family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user)
    query = select(RoadmapItem, Decision).join(Decision, Decision.id == RoadmapItem.decision_id).where(
        Decision.family_id == family_id,
        Decision.deleted_at.is_(None),
    )
    rows = db.execute(query.order_by(RoadmapItem.id.desc())).all()
    items = [
        _serialize(item)
        for item, decision in rows
        if decision_visible_to_actor(decision, actor_person_id=actor.actor_person_id, is_family_admin=actor.is_family_admin)
    ]
    return RoadmapListResponse(items=items)


@router.post("", response_model=RoadmapResponse, status_code=201)
def create_roadmap_item(
    payload: RoadmapCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    decision = db.get(Decision, payload.decision_id)
    if decision is None or decision.deleted_at is not None:
        raise HTTPException(status_code=404, detail="decision not found")
    require_family_feature(db, decision.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=decision.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if ctx is not None or x_dev_user:
        require_family_member(db, decision.family_id, actor.actor_id)
    if not decision_visible_to_actor(decision, actor_person_id=actor.actor_person_id, is_family_admin=actor.is_family_admin):
        raise HTTPException(status_code=403, detail="decision is not visible to this actor")

    policy = get_or_create_policy(db, decision.family_id)
    latest_score = _latest_score_run(db, decision.id)
    weighted_score = latest_score.weighted_total_1_to_5 if latest_score is not None else None
    meets_threshold = weighted_score is not None and weighted_score >= policy.threshold_1_to_5

    if not meets_threshold:
        if not payload.use_discretionary_budget:
            raise HTTPException(
                status_code=400,
                detail=f"decision score must meet threshold ({policy.threshold_1_to_5}) or use discretionary budget",
            )

        budget_person_id = _budget_person_id(decision)
        period = ensure_active_period(db, decision.family_id)
        ensure_person_allocation_in_period(db, decision.family_id, period, budget_person_id)
        allowance, used, remaining = person_remaining_in_period(db, period.id, budget_person_id)
        if remaining < 1:
            raise HTTPException(
                status_code=400,
                detail=f"discretionary budget exhausted for person (used {used} of {allowance} this period)",
            )

        db.add(
            DiscretionaryBudgetLedger(
                person_id=UUID(budget_person_id),
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
        dependencies_json=payload.dependencies,
    )
    db.add(item)
    decision.status = DecisionStatusEnum.scheduled
    decision.updated_at = utc_now()
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
            actor=actor.actor_id,
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
        actor=actor.actor_id,
        event_type="roadmap_item_created",
        summary=f"Roadmap item created for {decision.title}",
        topic=decision.title,
        status=item.status,
        payload={"roadmap_item_id": item.id, "decision_id": item.decision_id, "due_at": item.end_date},
        emit_canonical=False,
    )
    db.commit()
    return _serialize(item)


@router.patch("/{roadmap_id}", response_model=RoadmapResponse)
def update_roadmap_item(
    roadmap_id: int,
    payload: RoadmapUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    item = db.get(RoadmapItem, roadmap_id)
    if item is None:
        raise HTTPException(status_code=404, detail="roadmap item not found")
    decision = db.get(Decision, item.decision_id)
    if decision is None or decision.deleted_at is not None:
        raise HTTPException(status_code=404, detail="decision not found")
    require_family_feature(db, decision.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=decision.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if ctx is not None or x_dev_user:
        require_family_member(db, decision.family_id, actor.actor_id)
    if not decision_visible_to_actor(decision, actor_person_id=actor.actor_person_id, is_family_admin=actor.is_family_admin):
        raise HTTPException(status_code=403, detail="roadmap item is not visible to this actor")

    if payload.bucket is not None:
        item.bucket = payload.bucket
    if payload.start_date is not None:
        item.start_date = payload.start_date
    if payload.end_date is not None:
        item.end_date = payload.end_date
    if payload.status is not None:
        item.status = payload.status
    if payload.dependencies is not None:
        item.dependencies_json = payload.dependencies

    decision.updated_at = utc_now()
    db.commit()
    db.refresh(item)
    try:
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
        publish_event(
            Subjects.ROADMAP_ITEM_UPDATED,
            {"roadmap_item_id": item.id, "decision_id": item.decision_id},
            actor=actor.actor_id,
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
        actor=actor.actor_id,
        event_type="roadmap_item_updated",
        summary=f"Roadmap item updated for {decision.title}",
        topic=decision.title,
        status=item.status,
        payload={"roadmap_item_id": item.id, "decision_id": item.decision_id, "due_at": item.end_date},
        emit_canonical=False,
    )
    db.commit()
    return _serialize(item)


@router.delete("/{roadmap_id}", status_code=204)
def delete_roadmap_item(
    roadmap_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    item = db.get(RoadmapItem, roadmap_id)
    if item is None:
        raise HTTPException(status_code=404, detail="roadmap item not found")
    decision = db.get(Decision, item.decision_id)
    if decision is None or decision.deleted_at is not None:
        raise HTTPException(status_code=404, detail="decision not found")
    require_family_feature(db, decision.family_id, "decision")
    actor = resolve_actor_access_context(db, family_id=decision.family_id, ctx=ctx, x_dev_user=x_dev_user)
    if ctx is not None or x_dev_user:
        require_family_member(db, decision.family_id, actor.actor_id)
    if not decision_visible_to_actor(decision, actor_person_id=actor.actor_person_id, is_family_admin=actor.is_family_admin):
        raise HTTPException(status_code=403, detail="roadmap item is not visible to this actor")

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
        if len(refunds) < len(debits):
            latest_debit = debits[-1]
            db.add(
                DiscretionaryBudgetLedger(
                    person_id=latest_debit.person_id,
                    period_id=latest_debit.period_id,
                    delta=1,
                    reason="discretionary_unschedule_refund",
                    decision_id=item.decision_id,
                )
            )

    db.delete(item)
    decision.updated_at = utc_now()
    db.commit()
    record_agent_event(
        db,
        family_id=decision.family_id,
        domain="decision",
        source_agent="decision-api.roadmap",
        actor=actor.actor_id,
        event_type="roadmap_item_deleted",
        summary=f"Roadmap item removed for {decision.title}",
        topic=decision.title,
        status="deleted",
        payload={"roadmap_item_id": roadmap_id, "decision_id": decision.id},
        emit_canonical=False,
    )
    db.commit()
