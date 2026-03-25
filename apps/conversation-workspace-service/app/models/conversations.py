from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Conversation(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    family_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    visibility_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="participants")
    space_type: Mapped[str] = mapped_column(String(32), nullable=False, default="none", index=True)
    linked_records_json: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    primary_assistant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    latest_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_message_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConversationParticipant(Base):
    __tablename__ = "conversation_participants"

    participant_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False, index=True)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    participant_kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    person_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    top_level_assistant: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    assistant_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("conversation_id", "actor_email", "top_level_assistant", name="uq_conversation_participants_identity"),
    )


class Message(Base):
    __tablename__ = "messages"

    message_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False, index=True)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sender_kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    sender_participant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("conversation_participants.participant_id", ondelete="SET NULL"), nullable=True, index=True)
    sender_label: Mapped[str] = mapped_column(String(255), nullable=False)
    top_level_assistant: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    reply_to_message_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("messages.message_id", ondelete="SET NULL"), nullable=True, index=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class MessageBlock(Base):
    __tablename__ = "message_blocks"

    block_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("messages.message_id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    block_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("message_id", "position", name="uq_message_blocks_position"),
    )


class Attachment(Base):
    __tablename__ = "attachments"

    attachment_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False, index=True)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    message_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("messages.message_id", ondelete="SET NULL"), nullable=True, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    preview_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    summary_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False, index=True)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    summary_type: Mapped[str] = mapped_column(String(24), nullable=False, default="on_demand")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    decisions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    open_questions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    referenced_files_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False, index=True)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    trigger_message_id: Mapped[str] = mapped_column(String(36), ForeignKey("messages.message_id", ondelete="CASCADE"), nullable=False, index=True)
    top_level_assistant: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    provider: Mapped[str] = mapped_column(String(24), nullable=False, default="gateway")
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    response_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DomainActivity(Base):
    __tablename__ = "domain_activity"

    activity_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False, index=True)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agent_runs.run_id", ondelete="SET NULL"), nullable=True, index=True)
    message_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("messages.message_id", ondelete="SET NULL"), nullable=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    detail_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ActionProposal(Base):
    __tablename__ = "action_proposals"

    action_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False, index=True)
    family_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_message_id: Mapped[str] = mapped_column(String(36), ForeignKey("messages.message_id", ondelete="CASCADE"), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="proposed", index=True)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ShareEvent(Base):
    __tablename__ = "share_events"

    share_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    family_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_conversation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_message_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    target_conversation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


Index("ix_messages_conversation_created", Message.conversation_id, Message.created_at)
Index("ix_conversations_family_updated", Conversation.family_id, Conversation.updated_at)
