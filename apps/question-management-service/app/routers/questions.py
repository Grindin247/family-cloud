from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.schemas.questions import (
    AnswerQuestionRequest,
    ClaimNextQuestionRequest,
    ClaimNextQuestionResponse,
    CreateQuestionRequest,
    ListQuestionsResponse,
    MarkQuestionAskedRequest,
    PurgeQuestionsRequest,
    PurgeQuestionsResponse,
    QuestionHistoryResponse,
    QuestionMutationResponse,
    QuestionViewerMeResponse,
    ResolveQuestionRequest,
    UpdateQuestionRequest,
)
from app.services.decision_api import ensure_family_access, get_family_context, get_me
from app.services.questions import (
    answer_question,
    claim_next_questions,
    create_or_update_question,
    delete_question,
    expire_questions,
    get_question,
    list_question_history,
    list_questions,
    mark_question_asked,
    purge_questions,
    question_response,
    resolve_question,
    update_question,
)

router = APIRouter(prefix="/v1", tags=["questions"])


def _is_internal_admin(x_internal_admin_token: str | None) -> bool:
    return bool(x_internal_admin_token and x_internal_admin_token == settings.internal_admin_token)


def _actor_email(
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
) -> str | None:
    value = x_forwarded_user or x_dev_user
    return value.strip().lower() if value else None


def _actor_label(actor_email: str | None, internal_admin: bool) -> str:
    if internal_admin:
        return "system-internal"
    return actor_email or "system"


def _ensure_access(*, family_id: int, actor_email: str | None, internal_admin: bool) -> str:
    ensure_family_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    return _actor_label(actor_email, internal_admin)


@router.get("/me", response_model=QuestionViewerMeResponse)
def me(actor_email: str | None = Depends(_actor_email)):
    return get_me(actor_email=actor_email)


@router.get("/families/{family_id}/viewer-context", response_model=dict[str, Any])
def viewer_context(
    family_id: int,
    actor_email: str | None = Depends(_actor_email),
    target_person_id: str | None = Query(default=None),
):
    return get_family_context(family_id=family_id, actor_email=actor_email, target_person_id=target_person_id)


@router.get("/families/{family_id}/questions", response_model=ListQuestionsResponse)
def list_family_questions(
    family_id: int,
    domain: str | None = Query(default=None),
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    urgency: str | None = Query(default=None),
    source_agent: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    expire_questions(db, family_id=family_id)
    db.commit()
    return {
        "items": list_questions(
            db,
            family_id=family_id,
            domain=domain,
            category=category,
            status=status,
            urgency=urgency,
            source_agent=source_agent,
            include_inactive=include_inactive,
        )
    }


@router.get("/families/{family_id}/questions/history", response_model=QuestionHistoryResponse)
def question_history(
    family_id: int,
    question_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    internal_admin = _is_internal_admin(x_internal_admin_token)
    _ensure_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    return list_question_history(db, family_id=family_id, question_id=question_id)


@router.post("/families/{family_id}/questions/claim-next", response_model=ClaimNextQuestionResponse)
def claim_next(
    family_id: int,
    payload: ClaimNextQuestionRequest,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    internal_admin = _is_internal_admin(x_internal_admin_token)
    actor = _ensure_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    result = claim_next_questions(
        db,
        family_id=family_id,
        agent_id=payload.agent_id,
        channel=payload.channel,
        actor=actor,
        lease_seconds=payload.lease_seconds,
        allow_merge=payload.allow_merge,
        force=payload.force,
        timezone_name=payload.local_timezone,
    )
    db.commit()
    return result


@router.post("/families/{family_id}/questions/purge", response_model=PurgeQuestionsResponse)
def purge_family_questions(
    family_id: int,
    payload: PurgeQuestionsRequest,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    internal_admin = _is_internal_admin(x_internal_admin_token)
    actor = _ensure_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    deleted = purge_questions(
        db,
        family_id=family_id,
        actor=actor,
        question_ids=payload.question_ids,
        domain=payload.domain,
        status=payload.status,
        category=payload.category,
        purge_all=payload.all,
    )
    db.commit()
    return {"deleted": deleted}


@router.post("/families/{family_id}/questions", response_model=QuestionMutationResponse, status_code=201)
def create_question(
    family_id: int,
    payload: CreateQuestionRequest,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    internal_admin = _is_internal_admin(x_internal_admin_token)
    actor = _ensure_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    result = create_or_update_question(
        db,
        family_id=family_id,
        domain=payload.domain,
        source_agent=payload.source_agent,
        topic=payload.topic,
        category=payload.category,
        topic_type=payload.topic_type,
        summary=payload.summary,
        prompt=payload.prompt,
        urgency=payload.urgency,
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


@router.patch("/families/{family_id}/questions/{question_id}", response_model=QuestionMutationResponse)
def patch_question(
    family_id: int,
    question_id: str,
    payload: UpdateQuestionRequest,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    internal_admin = _is_internal_admin(x_internal_admin_token)
    actor = _ensure_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    question = get_question(db, question_id)
    if question is None or question.family_id != family_id:
        raise HTTPException(status_code=404, detail="question not found")
    result = update_question(
        db,
        question=question,
        actor=actor,
        topic=payload.topic,
        summary=payload.summary,
        prompt=payload.prompt,
        urgency=payload.urgency,
        category=payload.category,
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


@router.post("/families/{family_id}/questions/{question_id}/asked", response_model=QuestionMutationResponse)
def asked_question(
    family_id: int,
    question_id: str,
    payload: MarkQuestionAskedRequest,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    internal_admin = _is_internal_admin(x_internal_admin_token)
    actor = _ensure_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    question = get_question(db, question_id)
    if question is None or question.family_id != family_id:
        raise HTTPException(status_code=404, detail="question not found")
    result = mark_question_asked(
        db,
        question=question,
        actor=actor,
        delivery_agent=payload.delivery_agent,
        delivery_channel=payload.delivery_channel,
        claim_token=payload.claim_token,
        delivery_context=payload.delivery_context,
    )
    db.commit()
    return result


@router.post("/families/{family_id}/questions/{question_id}/answer", response_model=QuestionMutationResponse)
def answer_family_question(
    family_id: int,
    question_id: str,
    payload: AnswerQuestionRequest,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    internal_admin = _is_internal_admin(x_internal_admin_token)
    actor = _ensure_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    question = get_question(db, question_id)
    if question is None or question.family_id != family_id:
        raise HTTPException(status_code=404, detail="question not found")
    result = answer_question(
        db,
        question=question,
        actor=actor,
        answer_text=payload.answer_text,
        status=payload.status,
        answer_sufficiency_state=payload.answer_sufficiency_state,
        resolution_note=payload.resolution_note,
        responded_at=payload.responded_at,
        outcome=payload.outcome,
        context_patch=payload.context_patch,
    )
    db.commit()
    return result


@router.post("/families/{family_id}/questions/{question_id}/resolve", response_model=QuestionMutationResponse)
def resolve_family_question(
    family_id: int,
    question_id: str,
    payload: ResolveQuestionRequest,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    internal_admin = _is_internal_admin(x_internal_admin_token)
    actor = _ensure_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    question = get_question(db, question_id)
    if question is None or question.family_id != family_id:
        raise HTTPException(status_code=404, detail="question not found")
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


@router.delete("/families/{family_id}/questions/{question_id}", status_code=204)
def delete_family_question(
    family_id: int,
    question_id: str,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
    x_internal_admin_token: str | None = Header(default=None, alias="X-Internal-Admin-Token"),
):
    internal_admin = _is_internal_admin(x_internal_admin_token)
    actor = _ensure_access(family_id=family_id, actor_email=actor_email, internal_admin=internal_admin)
    question = get_question(db, question_id)
    if question is None or question.family_id != family_id:
        raise HTTPException(status_code=404, detail="question not found")
    delete_question(db, question=question, actor=actor)
    db.commit()
    return Response(status_code=204)
