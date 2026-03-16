from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentSessionState(Base):
    """
    Durable, per-user state for agents that need multi-turn workflows.

    This is intentionally generic so multiple agents can share the same table.
    """

    __tablename__ = "agent_session_states"

    family_id: Mapped[int] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"), primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_email: Mapped[str] = mapped_column(String(255), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)

    status: Mapped[str] = mapped_column(String(32), default="active")
    state_jsonb: Mapped[dict] = mapped_column(postgresql.JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


Index("ix_agent_session_states_family_updated", AgentSessionState.family_id, AgentSessionState.updated_at)

