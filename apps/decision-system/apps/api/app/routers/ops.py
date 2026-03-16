from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth import AuthContext
from app.core.config import settings
from app.core.db import get_db
from app.schemas.ops import (
    AgentEvent,
    CreateAgentQuestionRequest,
    ListAgentQuestionsResponse,
    MarkAgentQuestionAskedRequest,
    MetricsQuery,
    MetricsQueryResponse,
    PlaybackQuery,
    PlaybackQueryResponse,
    ResolveAgentQuestionRequest,
    UpdateAgentQuestionRequest,
)
from app.services.access import require_family, require_family_member
from app.services.ops import (
    create_or_update_question,
    expire_questions,
    get_playback_timeline,
    get_question,
    latest_decision_health_snapshot,
    list_question_history,
    list_questions,
    mark_question_asked,
    query_metrics,
    record_agent_event,
    resolve_question,
    update_question,
)
from app.services.task_ops import latest_task_health_snapshot

router = APIRouter(prefix="/v1/family/{family_id}/ops", tags=["ops"])


def _actor(ctx: AuthContext | None, x_dev_user: str | None) -> str:
    if ctx is not None:
        return ctx.email
    if x_dev_user:
        return x_dev_user.strip().lower()
    return "system"


def _is_internal_admin(x_internal_admin_token: str | None) -> bool:
    return bool(x_internal_admin_token and x_internal_admin_token == settings.internal_admin_token)


def get_ops_auth_context(
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
) -> AuthContext | None:
    if _is_internal_admin(x_internal_admin_token):
        return None
    if settings.auth_mode == "none":
        return None
    email = x_forwarded_user or x_dev_user
    if not email:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User)")
    return AuthContext(email=email.strip().lower())


def _ensure_family_access(
    db: Session,
    *,
    family_id: int,
    ctx: AuthContext | None,
    x_dev_user: str | None,
    x_internal_admin_token: str | None,
) -> str:
    require_family(db, family_id)
    if _is_internal_admin(x_internal_admin_token):
        return "system-internal"
    if ctx is not None:
        require_family_member(db, family_id, ctx.email)
    return _actor(ctx, x_dev_user)


@router.get("/questions", response_model=ListAgentQuestionsResponse)
def list_agent_questions(
    family_id: int,
    domain: str | None = Query(default=None),
    status: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_ops_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _ensure_family_access(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    expire_questions(db, family_id=family_id)
    db.commit()
    return {"items": list_questions(db, family_id=family_id, domain=domain, status=status, include_inactive=include_inactive)}


@router.post("/questions", response_model=dict, status_code=201)
def create_agent_question(
    family_id: int,
    payload: CreateAgentQuestionRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_ops_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _ensure_family_access(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    result = create_or_update_question(
        db,
        family_id=family_id,
        domain=payload.domain,
        source_agent=payload.source_agent,
        topic=payload.topic,
        summary=payload.summary,
        prompt=payload.prompt,
        urgency=payload.urgency,
        topic_type=payload.topic_type,
        actor=actor,
        dedupe_key=payload.dedupe_key,
        expires_at=payload.expires_at,
        due_at=payload.due_at,
        answer_sufficiency_state=payload.answer_sufficiency_state,
        context=payload.context,
        artifact_refs=payload.artifact_refs,
    )
    db.commit()
    return result


@router.patch("/questions/{question_id}", response_model=dict)
def patch_agent_question(
    family_id: int,
    question_id: str,
    payload: UpdateAgentQuestionRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_ops_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _ensure_family_access(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    question = get_question(db, question_id)
    if question is None or question.family_id != family_id:
        raise HTTPException(status_code=404, detail="agent question not found")
    result = update_question(
        db,
        question=question,
        actor=actor,
        summary=payload.summary,
        prompt=payload.prompt,
        urgency=payload.urgency,
        topic_type=payload.topic_type,
        status=payload.status,
        expires_at=payload.expires_at,
        due_at=payload.due_at,
        answer_sufficiency_state=payload.answer_sufficiency_state,
        context_patch=payload.context_patch,
        artifact_refs=payload.artifact_refs,
    )
    db.commit()
    return result


@router.post("/questions/{question_id}/asked", response_model=dict)
def asked_agent_question(
    family_id: int,
    question_id: str,
    payload: MarkAgentQuestionAskedRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_ops_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _ensure_family_access(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    question = get_question(db, question_id)
    if question is None or question.family_id != family_id:
        raise HTTPException(status_code=404, detail="agent question not found")
    result = mark_question_asked(
        db,
        question=question,
        actor=actor,
        delivery_agent=payload.delivery_agent,
        delivery_context=payload.delivery_context,
    )
    db.commit()
    return result


@router.post("/questions/{question_id}/resolve", response_model=dict)
def resolve_agent_question_route(
    family_id: int,
    question_id: str,
    payload: ResolveAgentQuestionRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_ops_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _ensure_family_access(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    question = get_question(db, question_id)
    if question is None or question.family_id != family_id:
        raise HTTPException(status_code=404, detail="agent question not found")
    result = resolve_question(
        db,
        question=question,
        actor=actor,
        status=payload.status,
        resolution_note=payload.resolution_note,
        answer_sufficiency_state=payload.answer_sufficiency_state,
        context_patch=payload.context_patch,
    )
    db.commit()
    return result


@router.get("/questions/history", response_model=list[dict])
def get_agent_question_history(
    family_id: int,
    question_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_ops_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _ensure_family_access(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    return list_question_history(db, family_id=family_id, question_id=question_id)


@router.post("/events", response_model=dict, status_code=201)
def create_agent_event(
    family_id: int,
    payload: AgentEvent,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_ops_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    actor = _ensure_family_access(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    result = record_agent_event(
        db,
        family_id=family_id,
        domain=payload.domain,
        source_agent=payload.source_agent,
        actor=actor,
        event_type=payload.event_type,
        summary=payload.summary,
        topic=payload.topic,
        status=payload.status,
        value_number=payload.value_number,
        payload=payload.payload,
        created_at=payload.created_at,
    )
    db.commit()
    return result


@router.post("/metrics/query", response_model=MetricsQueryResponse)
def query_agent_metrics_route(
    family_id: int,
    payload: MetricsQuery,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_ops_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _ensure_family_access(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    return {"items": query_metrics(db, family_id=family_id, domain=payload.domain, start_at=payload.start_at, end_at=payload.end_at, metric_keys=payload.metric_keys)}


@router.post("/playback/query", response_model=PlaybackQueryResponse)
def query_agent_playback_route(
    family_id: int,
    payload: PlaybackQuery,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_ops_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    _ensure_family_access(db, family_id=family_id, ctx=ctx, x_dev_user=x_dev_user, x_internal_admin_token=x_internal_admin_token)
    return {"items": get_playback_timeline(db, family_id=family_id, domain=payload.domain, event_types=payload.event_types, start_at=payload.start_at, end_at=payload.end_at, limit=payload.limit)}


@router.get("/admin/decision-health-snapshot", response_model=dict)
def get_decision_health_snapshot(
    family_id: int,
    db: Session = Depends(get_db),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    if not _is_internal_admin(x_internal_admin_token):
        raise HTTPException(status_code=401, detail="invalid internal admin token")
    require_family(db, family_id)
    return latest_decision_health_snapshot(db, family_id=family_id)


@router.get("/admin/task-health-snapshot", response_model=dict)
def get_task_health_snapshot(
    family_id: int,
    db: Session = Depends(get_db),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    if not _is_internal_admin(x_internal_admin_token):
        raise HTTPException(status_code=401, detail="invalid internal admin token")
    require_family(db, family_id)
    return latest_task_health_snapshot()
