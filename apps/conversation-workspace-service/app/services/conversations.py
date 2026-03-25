from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
import re
from pathlib import Path
from typing import Any, Iterable
import uuid

from fastapi import UploadFile
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import raise_api_error
from app.models.conversations import (
    ActionProposal,
    AgentRun,
    Attachment,
    Conversation,
    ConversationParticipant,
    ConversationSummary,
    DomainActivity,
    Message,
    MessageBlock,
    ShareEvent,
)

ASSISTANT_DEFINITIONS = [
    {"assistant_id": "caleb", "label": "Caleb", "description": "Warm, grounded top-level family support."},
    {"assistant_id": "amelia", "label": "Amelia", "description": "Supportive top-level family assistant."},
]

MENTION_PATTERNS = {
    "caleb": re.compile(r"(?<!\w)@?caleb\b", re.IGNORECASE),
    "amelia": re.compile(r"(?<!\w)@?amelia\b", re.IGNORECASE),
}

DOMAIN_ACTIVITY_RULES: list[tuple[str, str, list[str]]] = [
    ("PlanningAgent", "PlanningAgent drafting a plan", ["plan", "meal", "habit", "routine", "schedule", "trip"]),
    ("ProfileAgent", "ProfileAgent updating preferences", ["preference", "profile", "relationship", "accessibility", "dietary", "mfa"]),
    ("FileAgent", "FileAgent organizing upload", ["file", "upload", "note", "document", "inbox", "pdf"]),
    ("EventAgent", "EventAgent recording family summary", ["summary", "remember", "decision", "what changed", "timeline"]),
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return normalized.strip("-") or "conversation"


def assistant_label(assistant_id: str) -> str:
    for item in ASSISTANT_DEFINITIONS:
        if item["assistant_id"] == assistant_id:
            return str(item["label"])
    return assistant_id.title()


def primary_email_for_person(person: dict[str, Any]) -> str | None:
    accounts = person.get("accounts")
    if not isinstance(accounts, dict):
        return None
    for key in ("email", "directory", "openclaw_sender_key"):
        values = accounts.get(key)
        if isinstance(values, list) and values:
            first = str(values[0]).strip().lower()
            if first:
                return first
    return None


def infer_domain_agents(text: str) -> list[tuple[str, str]]:
    lowered = text.lower()
    matches: list[tuple[str, str]] = []
    for agent_name, summary, keywords in DOMAIN_ACTIVITY_RULES:
        if any(keyword in lowered for keyword in keywords):
            matches.append((agent_name, summary))
    return matches


def detect_mentions(text: str) -> list[str]:
    mentioned: list[str] = []
    for assistant_id, pattern in MENTION_PATTERNS.items():
        if pattern.search(text):
            mentioned.append(assistant_id)
    return mentioned


def add_message_with_blocks(
    db: Session,
    *,
    conversation: Conversation,
    sender_kind: str,
    sender_label: str,
    sender_participant_id: str | None,
    body_text: str | None,
    reply_to_message_id: str | None = None,
    top_level_assistant: str | None = None,
    metadata: dict[str, Any] | None = None,
    blocks: list[dict[str, Any]] | None = None,
    attachments: list[Attachment] | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation.conversation_id,
        family_id=conversation.family_id,
        sender_kind=sender_kind,
        sender_participant_id=sender_participant_id,
        sender_label=sender_label,
        top_level_assistant=top_level_assistant,
        reply_to_message_id=reply_to_message_id,
        body_text=body_text,
        metadata_json=metadata or {},
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(message)
    db.flush()
    block_defs = blocks or [{"block_type": "markdown", "text_content": body_text or "", "data": {}}]
    for index, block in enumerate(block_defs):
        db.add(
            MessageBlock(
                message_id=message.message_id,
                position=index,
                block_type=str(block["block_type"]),
                text_content=block.get("text_content"),
                data_json=block.get("data", {}),
            )
        )
    for attachment in attachments or []:
        attachment.message_id = message.message_id
    preview = (body_text or "").strip()
    if preview:
        conversation.latest_message_preview = preview[:240]
    conversation.updated_at = utcnow()
    db.flush()
    return message


def conversation_title(conversation: Conversation, participants: list[ConversationParticipant]) -> str:
    if conversation.title:
        return conversation.title
    assistant_participants = [item for item in participants if item.participant_kind == "top_level_ai" and item.removed_at is None]
    if conversation.kind == "assistant" and assistant_participants:
        return assistant_participants[0].display_name
    labels = [item.display_name for item in participants if item.participant_kind == "human" and item.removed_at is None]
    if labels:
        return ", ".join(labels[:3])
    return "Untitled Chat"


def ensure_assistant_inboxes(
    db: Session,
    *,
    family_id: int,
    actor_email: str,
    actor_person_id: str,
    actor_display_name: str,
) -> None:
    participant_conversation_ids = (
        select(ConversationParticipant.conversation_id)
        .where(
            ConversationParticipant.family_id == family_id,
            ConversationParticipant.removed_at.is_(None),
            or_(
                ConversationParticipant.actor_email == actor_email,
                ConversationParticipant.person_id == actor_person_id,
            ),
        )
        .subquery()
    )
    existing = {
        str(item)
        for item in db.execute(
            select(ConversationParticipant.top_level_assistant)
            .join(Conversation, Conversation.conversation_id == ConversationParticipant.conversation_id)
            .where(
                Conversation.family_id == family_id,
                Conversation.kind == "assistant",
                Conversation.conversation_id.in_(select(participant_conversation_ids.c.conversation_id)),
                ConversationParticipant.participant_kind == "top_level_ai",
                ConversationParticipant.removed_at.is_(None),
            )
        ).scalars()
        if item
    }
    for definition in ASSISTANT_DEFINITIONS:
        assistant_id = str(definition["assistant_id"])
        if assistant_id in existing:
            continue
        conversation = Conversation(
            family_id=family_id,
            kind="assistant",
            title=str(definition["label"]),
            slug=assistant_id,
            visibility_scope="participants",
            space_type="none",
            linked_records_json=[],
            created_by=actor_email,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(conversation)
        db.flush()
        human = ConversationParticipant(
            conversation_id=conversation.conversation_id,
            family_id=family_id,
            participant_kind="human",
            actor_email=actor_email,
            person_id=actor_person_id,
            display_name=actor_display_name,
            role="owner",
        )
        assistant = ConversationParticipant(
            conversation_id=conversation.conversation_id,
            family_id=family_id,
            participant_kind="top_level_ai",
            display_name=str(definition["label"]),
            top_level_assistant=assistant_id,
            assistant_mode="active",
            role="assistant",
        )
        db.add_all([human, assistant])
        db.flush()
        conversation.primary_assistant_id = assistant.participant_id
        conversation.updated_at = utcnow()
        add_message_with_blocks(
            db,
            conversation=conversation,
            sender_kind="system",
            sender_label="System",
            sender_participant_id=None,
            body_text=f"{definition['label']} is ready in this private assistant chat.",
            blocks=[{"block_type": "markdown", "text_content": f"{definition['label']} is ready in this private assistant chat.", "data": {}}],
            metadata={"seed": True},
        )


def visible_conversations_query(*, family_id: int, actor_email: str, actor_person_id: str) -> Select[tuple[Conversation]]:
    participant_conversation_ids = (
        select(ConversationParticipant.conversation_id)
        .where(
            ConversationParticipant.family_id == family_id,
            ConversationParticipant.removed_at.is_(None),
            or_(
                ConversationParticipant.actor_email == actor_email,
                ConversationParticipant.person_id == actor_person_id,
            ),
        )
        .subquery()
    )
    return select(Conversation).where(
        Conversation.family_id == family_id,
        Conversation.archived_at.is_(None),
        or_(
            Conversation.visibility_scope == "family",
            Conversation.conversation_id.in_(select(participant_conversation_ids.c.conversation_id)),
            and_(Conversation.kind == "assistant", Conversation.created_by == actor_email),
        ),
    )


def get_active_participants(db: Session, conversation_id: str) -> list[ConversationParticipant]:
    return list(
        db.execute(
            select(ConversationParticipant)
            .where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.removed_at.is_(None),
            )
            .order_by(ConversationParticipant.joined_at.asc())
        ).scalars()
    )


def get_messages(db: Session, conversation_id: str) -> list[Message]:
    return list(
        db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        ).scalars()
    )


def get_blocks(db: Session, message_ids: Iterable[str]) -> dict[str, list[MessageBlock]]:
    ids = list(message_ids)
    if not ids:
        return {}
    rows = db.execute(
        select(MessageBlock)
        .where(MessageBlock.message_id.in_(ids))
        .order_by(MessageBlock.position.asc())
    ).scalars()
    grouped: dict[str, list[MessageBlock]] = {}
    for row in rows:
        grouped.setdefault(row.message_id, []).append(row)
    return grouped


def get_attachments_by_message(db: Session, message_ids: Iterable[str]) -> dict[str, list[Attachment]]:
    ids = list(message_ids)
    if not ids:
        return {}
    rows = db.execute(select(Attachment).where(Attachment.message_id.in_(ids))).scalars()
    grouped: dict[str, list[Attachment]] = {}
    for row in rows:
        if row.message_id is None:
            continue
        grouped.setdefault(row.message_id, []).append(row)
    return grouped


def summarize_messages(messages: list[Message]) -> tuple[str, list[str], list[str], list[str]]:
    relevant = [message for message in messages if (message.body_text or "").strip()]
    if not relevant:
        return ("No conversation content yet.", [], [], [])
    snippets = [f"{message.sender_label}: {(message.body_text or '').strip()}" for message in relevant[-6:]]
    summary = "Summary so far: " + " | ".join(snippets)
    decisions = [snippet for snippet in snippets if "decide" in snippet.lower()][:3]
    open_questions = [snippet for snippet in snippets if "?" in snippet][:3]
    files = [snippet for snippet in snippets if any(token in snippet.lower() for token in ("file", "upload", "note", "pdf"))][:3]
    return (summary[:1200], decisions, open_questions, files)


def build_transport_message(
    *,
    conversation: Conversation,
    participants: list[ConversationParticipant],
    actor_label: str,
    user_text: str,
    summaries: list[ConversationSummary],
    recent_messages: list[Message],
    targeted_assistant: str,
) -> str:
    participant_labels = ", ".join(participant.display_name for participant in participants)
    latest_summary = summaries[-1].summary if summaries else ""
    recent_excerpt = "\n".join(
        f"- {message.sender_label}: {(message.body_text or '').strip()}"
        for message in recent_messages[-settings.message_context_limit :]
        if (message.body_text or "").strip()
    )
    return "\n".join(
        [
            f"Transport: first-party family chat (preserve the same conversational behavior you use in Discord).",
            f"Conversation kind: {conversation.kind}",
            f"Conversation title: {conversation.title or conversation.slug or 'Untitled'}",
            f"Space type: {conversation.space_type}",
            f"Participants: {participant_labels}",
            f"Current speaker: {actor_label}",
            f"Target assistant: {assistant_label(targeted_assistant)}",
            f"Latest summary: {latest_summary or 'None'}",
            "Recent messages:",
            recent_excerpt or "- None",
            "",
            "New user message:",
            user_text,
        ]
    )


def select_assistant_for_message(
    *,
    conversation: Conversation,
    participants: list[ConversationParticipant],
    body_text: str,
    explicit_assistant_id: str | None,
    invoke_assistant: bool,
) -> str | None:
    def participant_for_assistant(assistant_id: str) -> ConversationParticipant | None:
        return next(
            (
                item
                for item in participants
                if item.top_level_assistant == assistant_id and item.removed_at is None
            ),
            None,
        )

    if conversation.kind == "assistant":
        assistant = next((item for item in participants if item.participant_kind == "top_level_ai"), None)
        return assistant.top_level_assistant if assistant is not None else None
    if explicit_assistant_id:
        return explicit_assistant_id
    mentions = detect_mentions(body_text)
    if mentions:
        for assistant_id in mentions:
            if participant_for_assistant(assistant_id) is not None:
                return assistant_id
    if not invoke_assistant:
        return None
    if conversation.primary_assistant_id:
        participant = next((item for item in participants if item.participant_id == conversation.primary_assistant_id), None)
        if participant and participant.top_level_assistant and participant.assistant_mode == "active":
            return participant.top_level_assistant
    assistant = next(
        (
            item
            for item in participants
            if item.participant_kind == "top_level_ai" and item.assistant_mode == "active"
        ),
        None,
    )
    return assistant.top_level_assistant if assistant is not None else None


def ensure_conversation_visible(
    db: Session,
    *,
    family_id: int,
    conversation_id: str,
    actor_email: str,
    actor_person_id: str,
) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.family_id != family_id or conversation.archived_at is not None:
        raise_api_error(404, "conversation_not_found", "conversation not found", {"conversation_id": conversation_id})
    if conversation.visibility_scope == "family":
        return conversation
    allowed = db.execute(
        select(ConversationParticipant)
        .where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.removed_at.is_(None),
            or_(
                ConversationParticipant.actor_email == actor_email,
                ConversationParticipant.person_id == actor_person_id,
            ),
        )
    ).scalar_one_or_none()
    if conversation.kind == "assistant" and conversation.created_by == actor_email:
        return conversation
    if allowed is None:
        raise_api_error(403, "conversation_access_denied", "conversation is not visible to this actor", {"conversation_id": conversation_id})
    return conversation


def serialize_attachment(row: Attachment) -> dict[str, Any]:
    return {
        "attachment_id": row.attachment_id,
        "file_name": row.file_name,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "storage_path": row.storage_path,
        "preview_url": row.preview_url,
        "created_at": row.created_at,
    }


def serialize_message(row: Message, *, blocks: dict[str, list[MessageBlock]], attachments: dict[str, list[Attachment]]) -> dict[str, Any]:
    return {
        "message_id": row.message_id,
        "sender_kind": row.sender_kind,
        "sender_label": row.sender_label,
        "top_level_assistant": row.top_level_assistant,
        "body_text": row.body_text,
        "metadata": row.metadata_json or {},
        "reply_to_message_id": row.reply_to_message_id,
        "created_at": row.created_at,
        "blocks": [
            {
                "block_id": block.block_id,
                "block_type": block.block_type,
                "text_content": block.text_content,
                "data": block.data_json or {},
                "position": block.position,
            }
            for block in blocks.get(row.message_id, [])
        ],
        "attachments": [serialize_attachment(item) for item in attachments.get(row.message_id, [])],
    }


def serialize_participant(row: ConversationParticipant) -> dict[str, Any]:
    return {
        "participant_id": row.participant_id,
        "participant_kind": row.participant_kind,
        "actor_email": row.actor_email,
        "person_id": row.person_id,
        "display_name": row.display_name,
        "top_level_assistant": row.top_level_assistant,
        "assistant_mode": row.assistant_mode,
        "role": row.role,
        "joined_at": row.joined_at,
    }


def serialize_conversation(db: Session, row: Conversation, *, include_messages: bool = True) -> dict[str, Any]:
    participants = get_active_participants(db, row.conversation_id)
    messages = get_messages(db, row.conversation_id) if include_messages else []
    blocks = get_blocks(db, [message.message_id for message in messages])
    attachments = get_attachments_by_message(db, [message.message_id for message in messages])
    summaries = list(
        db.execute(
            select(ConversationSummary)
            .where(ConversationSummary.conversation_id == row.conversation_id)
            .order_by(ConversationSummary.created_at.desc())
            .limit(5)
        ).scalars()
    )
    domain_activity = list(
        db.execute(
            select(DomainActivity)
            .where(DomainActivity.conversation_id == row.conversation_id)
            .order_by(DomainActivity.updated_at.desc())
            .limit(10)
        ).scalars()
    )
    action_proposals = list(
        db.execute(
            select(ActionProposal)
            .where(ActionProposal.conversation_id == row.conversation_id)
            .order_by(ActionProposal.created_at.desc())
            .limit(10)
        ).scalars()
    )
    return {
        "conversation_id": row.conversation_id,
        "family_id": row.family_id,
        "kind": row.kind,
        "title": conversation_title(row, participants),
        "visibility_scope": row.visibility_scope,
        "space_type": row.space_type,
        "linked_records": row.linked_records_json or [],
        "primary_assistant_id": row.primary_assistant_id,
        "latest_summary": row.latest_summary,
        "latest_message_preview": row.latest_message_preview,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "participants": [serialize_participant(item) for item in participants],
        "messages": [serialize_message(message, blocks=blocks, attachments=attachments) for message in messages],
        "summaries": [
            {
                "summary_id": item.summary_id,
                "summary_type": item.summary_type,
                "summary": item.summary,
                "decisions": item.decisions_json or [],
                "open_questions": item.open_questions_json or [],
                "referenced_files": item.referenced_files_json or [],
                "created_by": item.created_by,
                "created_at": item.created_at,
            }
            for item in reversed(summaries)
        ],
        "domain_activity": [
            {
                "activity_id": item.activity_id,
                "agent_name": item.agent_name,
                "state": item.state,
                "summary": item.summary,
                "detail": item.detail_json or {},
                "run_id": item.run_id,
                "message_id": item.message_id,
                "updated_at": item.updated_at,
            }
            for item in domain_activity
        ],
        "action_proposals": [
            {
                "action_id": item.action_id,
                "action_type": item.action_type,
                "title": item.title,
                "summary": item.summary,
                "status": item.status,
                "request": item.request_json or {},
                "result": item.result_json or {},
                "source_conversation_id": item.source_conversation_id,
                "source_message_id": item.source_message_id,
                "created_by": item.created_by,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            for item in action_proposals
        ],
    }


def save_upload(
    *,
    file: UploadFile,
    family_id: int,
    conversation_id: str,
) -> tuple[str, int]:
    settings.uploads_path.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", file.filename or "upload.bin")
    target_dir = settings.uploads_path / str(family_id) / conversation_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_name = f"{uuid.uuid4()}-{safe_name}"
    destination = target_dir / target_name
    total = 0
    with destination.open("wb") as handle:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            handle.write(chunk)
    return (str(destination), total)
