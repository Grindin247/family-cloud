import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.models.entities import Decision, DecisionQueueItem, DecisionScore, DecisionStatusEnum, FamilyMember, Goal, RoadmapItem
from app.schemas.decisions import (
    DecisionCreate,
    DecisionGoalScoreResponse,
    DecisionListResponse,
    DecisionResponse,
    DecisionScoreRequest,
    DecisionScoreResponse,
    DecisionScoreSummaryResponse,
    DecisionUpdate,
)
from app.services.scoring import GoalScoreInput, compute_weighted_score, threshold_outcome
from app.services.access import require_family_admin, require_family_feature, require_family_member
from app.services.event_bus import publish_event
from app.services.family_events import make_backend_event_payload
from app.services.ops import record_agent_event
from agents.common.events.subjects import Subjects
from agents.common.family_events import publish_event as publish_family_event
from app.services.memory import create_document_with_embeddings

router = APIRouter(prefix="/v1/decisions", tags=["decisions"])


def _emit_decision_event(
    *,
    decision: Decision,
    actor: str,
    event_type: str,
    payload: dict,
    tags: list[str] | None = None,
) -> None:
    event = make_backend_event_payload(
        family_id=decision.family_id,
        domain="decision",
        event_type=event_type,
        actor_id=actor,
        actor_type="user",
        subject_id=str(decision.id),
        subject_type="decision",
        payload=payload,
        source_agent_id="DecisionAgent",
        source_runtime="backend",
        tags=tags or json.loads(decision.tags or "[]"),
    )
    publish_family_event(event)


def _decision_score_summary(db: Session, decision: Decision) -> DecisionScoreSummaryResponse | None:
    rows = db.execute(
        select(DecisionScore, Goal).join(Goal, Goal.id == DecisionScore.goal_id).where(
            DecisionScore.decision_id == decision.id,
            DecisionScore.version == decision.version,
        )
    ).all()
    if not rows:
        return None

    weighted_inputs: list[GoalScoreInput] = []
    goal_scores: list[DecisionGoalScoreResponse] = []
    for score, goal in rows:
        weighted_inputs.append(GoalScoreInput(weight=goal.weight, score=score.score_1_to_5))
        goal_scores.append(
            DecisionGoalScoreResponse(
                goal_id=score.goal_id,
                goal_name=goal.name,
                goal_weight=goal.weight,
                score_1_to_5=score.score_1_to_5,
                rationale=score.rationale,
                computed_by=score.computed_by,
                version=score.version,
            )
        )

    return DecisionScoreSummaryResponse(
        weighted_total_1_to_5=compute_weighted_score(weighted_inputs, normalize_to=5),
        weighted_total_0_to_100=compute_weighted_score(weighted_inputs, normalize_to=100),
        goal_scores=goal_scores,
    )


def _to_decision_response(db: Session, decision: Decision, include_scores: bool = False) -> DecisionResponse:
    return DecisionResponse(
        id=decision.id,
        family_id=decision.family_id,
        created_by_member_id=decision.created_by_member_id,
        owner_member_id=decision.owner_member_id,
        title=decision.title,
        description=decision.description,
        cost=decision.cost,
        urgency=decision.urgency,
        target_date=decision.target_date,
        tags=json.loads(decision.tags or "[]"),
        status=decision.status.value,
        notes=decision.notes,
        version=decision.version,
        created_at=decision.created_at,
        score_summary=_decision_score_summary(db, decision) if include_scores else None,
    )


def _ensure_decision_exists(db: Session, decision_id: int) -> Decision:
    decision = db.get(Decision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="decision not found")
    return decision


@router.get("", response_model=DecisionListResponse)
def list_decisions(
    family_id: int | None = Query(default=None),
    include_scores: bool = Query(default=False),
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    query = select(Decision)
    if ctx is not None:
        query = query.join(FamilyMember, FamilyMember.family_id == Decision.family_id).where(FamilyMember.email == ctx.email)
    if family_id is not None:
        require_family_feature(db, family_id, "decision")
        if ctx is not None:
            require_family_member(db, family_id, ctx.email)
        query = query.where(Decision.family_id == family_id)
    decisions = db.execute(query.order_by(Decision.created_at.desc())).scalars().all()
    return DecisionListResponse(items=[_to_decision_response(db, item, include_scores=include_scores) for item in decisions])


@router.get("/{decision_id}", response_model=DecisionResponse)
def get_decision(
    decision_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    decision = _ensure_decision_exists(db, decision_id)
    if ctx is not None:
        require_family_feature(db, decision.family_id, "decision")
        require_family_member(db, decision.family_id, ctx.email)
    return _to_decision_response(db, decision, include_scores=True)


@router.post("", response_model=DecisionResponse, status_code=201)
def create_decision(
    payload: DecisionCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    created_by_member_id = payload.created_by_member_id
    require_family_feature(db, payload.family_id, "decision")
    if ctx is not None:
        member = require_family_member(db, payload.family_id, ctx.email)
        created_by_member_id = member.id
        if payload.owner_member_id is not None:
            # Ensure owner belongs to the same family.
            owner = db.get(FamilyMember, payload.owner_member_id)
            if owner is None or owner.family_id != payload.family_id:
                raise HTTPException(status_code=400, detail="owner_member_id must belong to the decision family")
    if created_by_member_id is None:
        raise HTTPException(status_code=400, detail="created_by_member_id is required when auth is disabled")

    decision = Decision(
        family_id=payload.family_id,
        created_by_member_id=created_by_member_id,
        owner_member_id=payload.owner_member_id,
        title=payload.title,
        description=payload.description,
        cost=payload.cost,
        urgency=payload.urgency,
        target_date=payload.target_date,
        tags=json.dumps(payload.tags),
        notes=payload.notes,
        status=DecisionStatusEnum.draft,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    try:
        create_document_with_embeddings(
            db,
            family_id=decision.family_id,
            type="decision",
            text_value=f"Decision created: {decision.title}\n\n{decision.description}",
            source_refs=[],
        )
        db.commit()
    except Exception:
        db.rollback()
    try:
        publish_event(
            Subjects.DECISION_CREATED,
            {"decision_id": decision.id, "title": decision.title},
            actor=ctx.email if ctx is not None else "system",
            family_id=decision.family_id,
            source="decision-api.decisions",
        )
    except Exception:
        pass
    try:
        _emit_decision_event(
            decision=decision,
            actor=ctx.email if ctx is not None else "system",
            event_type="decision.created",
            payload={
                "decision_id": decision.id,
                "title": decision.title,
                "urgency": decision.urgency,
                "target_date": decision.target_date.isoformat() if decision.target_date else None,
                "status": decision.status.value,
            },
        )
    except Exception:
        pass
    record_agent_event(
        db,
        family_id=decision.family_id,
        domain="decision",
        source_agent="decision-api.decisions",
        actor=ctx.email if ctx is not None else "system",
        event_type="decision_created",
        summary=f"Decision created: {decision.title}",
        topic=decision.title,
        status=decision.status.value,
        payload={"decision_id": decision.id, "urgency": decision.urgency, "target_date": decision.target_date},
    )
    db.commit()
    return _to_decision_response(db, decision)


@router.patch("/{decision_id}", response_model=DecisionResponse)
def update_decision(
    decision_id: int,
    payload: DecisionUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    decision = _ensure_decision_exists(db, decision_id)
    if ctx is not None:
        require_family_feature(db, decision.family_id, "decision")
        require_family_member(db, decision.family_id, ctx.email)

    if payload.owner_member_id is not None:
        if ctx is not None:
            owner = db.get(FamilyMember, payload.owner_member_id)
            if owner is None or owner.family_id != decision.family_id:
                raise HTTPException(status_code=400, detail="owner_member_id must belong to the decision family")
        decision.owner_member_id = payload.owner_member_id
    if payload.title is not None:
        decision.title = payload.title
    if payload.description is not None:
        decision.description = payload.description
    if payload.cost is not None:
        decision.cost = payload.cost
    if payload.urgency is not None:
        decision.urgency = payload.urgency
    if payload.target_date is not None:
        decision.target_date = payload.target_date
    if payload.tags is not None:
        decision.tags = json.dumps(payload.tags)
    if payload.notes is not None:
        decision.notes = payload.notes

    db.commit()
    db.refresh(decision)
    try:
        create_document_with_embeddings(
            db,
            family_id=decision.family_id,
            type="decision",
            text_value=f"Decision updated: {decision.title}\n\n{decision.description}",
            source_refs=[],
        )
        db.commit()
    except Exception:
        db.rollback()
    try:
        publish_event(
            Subjects.DECISION_UPDATED,
            {"decision_id": decision.id},
            actor=ctx.email if ctx is not None else "system",
            family_id=decision.family_id,
            source="decision-api.decisions",
        )
    except Exception:
        pass
    try:
        _emit_decision_event(
            decision=decision,
            actor=ctx.email if ctx is not None else "system",
            event_type="decision.updated",
            payload={
                "decision_id": decision.id,
                "title": decision.title,
                "urgency": decision.urgency,
                "target_date": decision.target_date.isoformat() if decision.target_date else None,
                "status": decision.status.value,
            },
        )
    except Exception:
        pass
    record_agent_event(
        db,
        family_id=decision.family_id,
        domain="decision",
        source_agent="decision-api.decisions",
        actor=ctx.email if ctx is not None else "system",
        event_type="decision_updated",
        summary=f"Decision updated: {decision.title}",
        topic=decision.title,
        status=decision.status.value,
        payload={"decision_id": decision.id, "urgency": decision.urgency, "target_date": decision.target_date},
    )
    db.commit()
    return _to_decision_response(db, decision)


@router.delete("/{decision_id}", status_code=204)
def delete_decision(
    decision_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    decision = _ensure_decision_exists(db, decision_id)
    if ctx is not None:
        require_family_admin(db, decision.family_id, ctx.email)
    record_agent_event(
        db,
        family_id=decision.family_id,
        domain="decision",
        source_agent="decision-api.decisions",
        actor=ctx.email if ctx is not None else "system",
        event_type="decision_deleted",
        summary=f"Decision deleted: {decision.title}",
        topic=decision.title,
        status="deleted",
        payload={"decision_id": decision.id},
    )
    db.query(DecisionScore).filter(DecisionScore.decision_id == decision.id).delete()
    db.query(DecisionQueueItem).filter(DecisionQueueItem.decision_id == decision.id).delete()
    db.query(RoadmapItem).filter(RoadmapItem.decision_id == decision.id).delete()
    db.delete(decision)
    db.commit()


@router.post("/{decision_id}/score", response_model=DecisionScoreResponse)
def manual_score_decision(
    decision_id: int,
    payload: DecisionScoreRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    decision = _ensure_decision_exists(db, decision_id)
    if ctx is not None:
        require_family_member(db, decision.family_id, ctx.email)

    goal_ids = [item.goal_id for item in payload.goal_scores]
    goals = db.execute(
        select(Goal).where(
            Goal.id.in_(goal_ids),
            Goal.family_id == decision.family_id,
            Goal.active.is_(True),
        )
    ).scalars().all()

    goal_map = {goal.id: goal for goal in goals}
    if len(goal_map) != len(set(goal_ids)):
        raise HTTPException(status_code=400, detail="all scored goals must exist, be active, and belong to decision family")

    db.query(DecisionScore).filter(
        DecisionScore.decision_id == decision.id,
        DecisionScore.version == decision.version,
    ).delete()

    weighted_inputs: list[GoalScoreInput] = []
    for item in payload.goal_scores:
        goal = goal_map[item.goal_id]
        db.add(
            DecisionScore(
                decision_id=decision.id,
                goal_id=item.goal_id,
                score_1_to_5=item.score_1_to_5,
                rationale=item.rationale,
                computed_by=payload.computed_by,
                version=decision.version,
            )
        )
        weighted_inputs.append(GoalScoreInput(weight=goal.weight, score=item.score_1_to_5))

    weighted_1_to_5 = compute_weighted_score(weighted_inputs, normalize_to=5)
    weighted_0_to_100 = compute_weighted_score(weighted_inputs, normalize_to=100)
    routed_to = threshold_outcome(weighted_1_to_5, payload.threshold_1_to_5)

    queue_item_id: int | None = None
    if routed_to == "queue":
        decision.status = DecisionStatusEnum.queued
        queue_item = db.execute(
            select(DecisionQueueItem).where(DecisionQueueItem.decision_id == decision.id)
        ).scalar_one_or_none()
        if queue_item is None:
            max_rank = db.execute(select(func.max(DecisionQueueItem.rank))).scalar_one()
            queue_item = DecisionQueueItem(
                decision_id=decision.id,
                priority=decision.urgency or 3,
                due_date=decision.target_date,
                rank=(max_rank or 0) + 1,
            )
            db.add(queue_item)
            db.flush()
        queue_item_id = queue_item.id
    else:
        decision.status = DecisionStatusEnum.needs_work

    db.commit()
    try:
        create_document_with_embeddings(
            db,
            family_id=decision.family_id,
            type="rationale",
            text_value=f"Decision scored: decision_id={decision.id} weighted_1_to_5={weighted_1_to_5} threshold={payload.threshold_1_to_5} routed_to={routed_to}. Scores: {payload.goal_scores}",
            source_refs=[],
        )
        db.commit()
    except Exception:
        db.rollback()
    try:
        publish_event(
            Subjects.DECISION_SCORED,
            {
                "decision_id": decision.id,
                "weighted_total_1_to_5": weighted_1_to_5,
                "threshold_1_to_5": payload.threshold_1_to_5,
                "routed_to": routed_to,
                "status": decision.status.value,
            },
            actor=ctx.email if ctx is not None else "system",
            family_id=decision.family_id,
            source="decision-api.decisions",
        )
    except Exception:
        pass
    try:
        _emit_decision_event(
            decision=decision,
            actor=ctx.email if ctx is not None else "system",
            event_type="decision.score_calculated",
            payload={
                "decision_id": decision.id,
                "title": decision.title,
                "score_type": "goal_alignment",
                "score_value": weighted_1_to_5,
                "threshold_1_to_5": payload.threshold_1_to_5,
                "routed_to": routed_to,
                "status": decision.status.value,
            },
        )
    except Exception:
        pass
    record_agent_event(
        db,
        family_id=decision.family_id,
        domain="decision",
        source_agent="decision-api.decisions",
        actor=ctx.email if ctx is not None else "system",
        event_type="decision_scored",
        summary=f"Decision scored: {decision.title}",
        topic=decision.title,
        status=decision.status.value,
        value_number=weighted_1_to_5,
        payload={
            "decision_id": decision.id,
            "threshold_1_to_5": payload.threshold_1_to_5,
            "routed_to": routed_to,
            "weighted_total_0_to_100": weighted_0_to_100,
        },
    )
    if weighted_1_to_5 < payload.threshold_1_to_5:
        record_agent_event(
            db,
            family_id=decision.family_id,
            domain="decision",
            source_agent="decision-api.decisions",
            actor=ctx.email if ctx is not None else "system",
            event_type="decision_below_threshold",
            summary=f"Decision below threshold: {decision.title}",
            topic=decision.title,
            status=decision.status.value,
            value_number=weighted_1_to_5,
            payload={"decision_id": decision.id, "threshold_1_to_5": payload.threshold_1_to_5},
        )
    db.commit()

    status_value = decision.status.value
    return DecisionScoreResponse(
        decision_id=decision.id,
        weighted_total_1_to_5=weighted_1_to_5,
        weighted_total_0_to_100=weighted_0_to_100,
        threshold_1_to_5=payload.threshold_1_to_5,
        routed_to=routed_to,
        status=status_value,
        queue_item_id=queue_item_id,
    )


@router.post("/{decision_id}/queue")
def queue_decision(
    decision_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    decision = _ensure_decision_exists(db, decision_id)
    if ctx is not None:
        require_family_member(db, decision.family_id, ctx.email)
    queue_item = db.execute(
        select(DecisionQueueItem).where(DecisionQueueItem.decision_id == decision.id)
    ).scalar_one_or_none()

    if queue_item is None:
        max_rank = db.execute(select(func.max(DecisionQueueItem.rank))).scalar_one()
        queue_item = DecisionQueueItem(
            decision_id=decision.id,
            priority=decision.urgency or 3,
            due_date=decision.target_date,
            rank=(max_rank or 0) + 1,
        )
        db.add(queue_item)

    decision.status = DecisionStatusEnum.queued
    db.commit()
    db.refresh(queue_item)
    try:
        _emit_decision_event(
            decision=decision,
            actor=ctx.email if ctx is not None else "system",
            event_type="decision.updated",
            payload={
                "decision_id": decision.id,
                "title": decision.title,
                "status": decision.status.value,
                "queue_item_id": queue_item.id,
            },
        )
    except Exception:
        pass
    record_agent_event(
        db,
        family_id=decision.family_id,
        domain="decision",
        source_agent="decision-api.decisions",
        actor=ctx.email if ctx is not None else "system",
        event_type="decision_queued",
        summary=f"Decision queued: {decision.title}",
        topic=decision.title,
        status=decision.status.value,
        payload={"decision_id": decision.id, "queue_item_id": queue_item.id},
    )
    db.commit()
    return {"decision_id": decision_id, "status": "queued", "queue_item_id": queue_item.id}


@router.post("/{decision_id}/status")
def update_status(
    decision_id: int,
    status: str,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
):
    decision = _ensure_decision_exists(db, decision_id)
    if ctx is not None:
        require_family_member(db, decision.family_id, ctx.email)
    previous_status = decision.status.value
    allowed = {item.value: item for item in DecisionStatusEnum}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="invalid status")
    decision.status = allowed[status]
    db.commit()
    canonical_event_type = "decision.updated"
    if status == DecisionStatusEnum.discretionary_approved.value:
        canonical_event_type = "decision.approved"
    elif status == DecisionStatusEnum.rejected.value:
        canonical_event_type = "decision.rejected"
    try:
        _emit_decision_event(
            decision=decision,
            actor=ctx.email if ctx is not None else "system",
            event_type=canonical_event_type,
            payload={
                "decision_id": decision.id,
                "title": decision.title,
                "previous_status": previous_status,
                "status": decision.status.value,
            },
        )
    except Exception:
        pass
    event_type = "decision_completed" if status == DecisionStatusEnum.done.value else "decision_status_updated"
    record_agent_event(
        db,
        family_id=decision.family_id,
        domain="decision",
        source_agent="decision-api.decisions",
        actor=ctx.email if ctx is not None else "system",
        event_type=event_type,
        summary=f"Decision status changed: {decision.title} -> {status}",
        topic=decision.title,
        status=status,
        payload={"decision_id": decision.id, "previous_status": previous_status},
    )
    db.commit()
    return {"decision_id": decision_id, "status": decision.status.value}
