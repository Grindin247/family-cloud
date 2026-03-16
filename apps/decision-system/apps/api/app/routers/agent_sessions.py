from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, get_auth_context
from app.core.db import get_db
from app.models.agent_sessions import AgentSessionState
from app.schemas.agent_sessions import AgentSessionResponse, AgentSessionUpsertRequest
from app.services.access import require_family, require_family_member

router = APIRouter(prefix="/v1/family/{family_id}/agents", tags=["agents"])


def _actor_email(ctx: AuthContext | None, x_dev_user: str | None) -> str:
    if ctx is not None:
        return ctx.email
    if x_dev_user:
        return x_dev_user.strip().lower()
    # Auth disabled and no dev header: fall back to a shared actor.
    return "system"


@router.get("/{agent_name}/sessions/{session_id}", response_model=AgentSessionResponse)
def get_agent_session(
    family_id: int,
    agent_name: str,
    session_id: str,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family(db, family_id)
    if ctx is not None:
        require_family_member(db, family_id, ctx.email)
    actor = _actor_email(ctx, x_dev_user)
    row = (
        db.query(AgentSessionState)
        .filter(
            AgentSessionState.family_id == family_id,
            AgentSessionState.agent_name == agent_name,
            AgentSessionState.actor_email == actor,
            AgentSessionState.session_id == session_id,
        )
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="agent session not found")
    return AgentSessionResponse(
        family_id=row.family_id,
        agent_name=row.agent_name,
        actor_email=row.actor_email,
        session_id=row.session_id,
        status=row.status,
        state=row.state_jsonb or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.put("/{agent_name}/sessions/{session_id}", response_model=AgentSessionResponse)
def upsert_agent_session(
    family_id: int,
    agent_name: str,
    session_id: str,
    payload: AgentSessionUpsertRequest,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family(db, family_id)
    if ctx is not None:
        require_family_member(db, family_id, ctx.email)
    actor = _actor_email(ctx, x_dev_user)
    now = datetime.now(timezone.utc)
    row = (
        db.query(AgentSessionState)
        .filter(
            AgentSessionState.family_id == family_id,
            AgentSessionState.agent_name == agent_name,
            AgentSessionState.actor_email == actor,
            AgentSessionState.session_id == session_id,
        )
        .one_or_none()
    )
    if row is None:
        row = AgentSessionState(
            family_id=family_id,
            agent_name=agent_name,
            actor_email=actor,
            session_id=session_id,
            status=payload.status or "active",
            state_jsonb=payload.state or {},
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        if payload.status is not None:
            row.status = payload.status
        row.state_jsonb = payload.state or {}
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return AgentSessionResponse(
        family_id=row.family_id,
        agent_name=row.agent_name,
        actor_email=row.actor_email,
        session_id=row.session_id,
        status=row.status,
        state=row.state_jsonb or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.delete("/{agent_name}/sessions/{session_id}", status_code=204)
def delete_agent_session(
    family_id: int,
    agent_name: str,
    session_id: str,
    db: Session = Depends(get_db),
    ctx: AuthContext | None = Depends(get_auth_context),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    require_family(db, family_id)
    if ctx is not None:
        require_family_member(db, family_id, ctx.email)
    actor = _actor_email(ctx, x_dev_user)
    row = (
        db.query(AgentSessionState)
        .filter(
            AgentSessionState.family_id == family_id,
            AgentSessionState.agent_name == agent_name,
            AgentSessionState.actor_email == actor,
            AgentSessionState.session_id == session_id,
        )
        .one_or_none()
    )
    if row is None:
        return
    db.delete(row)
    db.commit()

