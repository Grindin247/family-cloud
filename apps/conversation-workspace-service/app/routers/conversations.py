from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, get_db
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
    ShareEvent,
)
from app.schemas.conversations import (
    ActionMutationResponse,
    AssistantInviteRequest,
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationResponse,
    ConvertRequest,
    MessageCreateRequest,
    ShareRequest,
    SummaryCreateRequest,
    ViewerContextResponse,
    ViewerMeResponse,
)
from app.services.conversations import (
    ASSISTANT_DEFINITIONS,
    add_message_with_blocks,
    assistant_label,
    build_transport_message,
    ensure_assistant_inboxes,
    ensure_conversation_visible,
    get_active_participants,
    get_messages,
    infer_domain_agents,
    primary_email_for_person,
    save_upload,
    select_assistant_for_message,
    serialize_conversation,
    summarize_messages,
    utcnow,
    visible_conversations_query,
)
from app.services.decision_api import ensure_family_access, get_family_context, get_family_persons, get_me
from app.services.realtime import realtime_manager
from app.services.runtime import OpenClawRuntimeAdapter

router = APIRouter(prefix="/v1", tags=["conversations"])
runtime_adapter = OpenClawRuntimeAdapter()


def _actor_email(
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
) -> str | None:
    value = x_forwarded_user or x_dev_user
    return value.strip().lower() if value else None


def _actor_context(*, family_id: int, actor_email: str | None):
    ensure_family_access(family_id=family_id, actor_email=actor_email, internal_admin=False)
    if not actor_email:
        raise_api_error(401, "missing_auth", "missing auth header (X-Forwarded-User or X-Dev-User)")
    family_context = get_family_context(family_id=family_id, actor_email=actor_email)
    people = get_family_persons(family_id=family_id, actor_email=actor_email, internal_admin=False)
    actor_person_id = str(family_context.get("actor_person_id") or family_context.get("person_id") or "")
    actor_display_name = next(
        (str(person.get("display_name")) for person in people if str(person.get("person_id")) == actor_person_id),
        actor_email,
    )
    return actor_person_id, actor_display_name, family_context, people


def _find_human_participant(participants: list[ConversationParticipant], *, actor_email: str, actor_person_id: str) -> ConversationParticipant | None:
    return next(
        (
            item
            for item in participants
            if item.participant_kind == "human"
            and (item.actor_email == actor_email or item.person_id == actor_person_id)
            and item.removed_at is None
        ),
        None,
    )


@router.get("/me", response_model=ViewerMeResponse)
def viewer_me(actor_email: str | None = Depends(_actor_email)):
    return ViewerMeResponse.model_validate(get_me(actor_email=actor_email))


@router.get("/families/{family_id}/viewer-context", response_model=ViewerContextResponse)
def viewer_context(family_id: int, actor_email: str | None = Depends(_actor_email)):
    actor_person_id, _, family_context, people = _actor_context(family_id=family_id, actor_email=actor_email)
    return ViewerContextResponse(
        family_id=family_id,
        family_slug=str(family_context.get("family_slug") or ""),
        actor_email=actor_email or "",
        actor_person_id=actor_person_id,
        target_person_id=str(family_context.get("target_person_id") or actor_person_id),
        is_family_admin=bool(family_context.get("is_family_admin")),
        assistants=[definition for definition in ASSISTANT_DEFINITIONS],
        persons=people,
    )


@router.get("/families/{family_id}/conversations", response_model=ConversationListResponse)
def list_conversations(
    family_id: int,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
):
    actor_person_id, actor_display_name, _, _ = _actor_context(family_id=family_id, actor_email=actor_email)
    ensure_assistant_inboxes(
        db,
        family_id=family_id,
        actor_email=actor_email or "",
        actor_person_id=actor_person_id,
        actor_display_name=actor_display_name,
    )
    db.commit()
    conversations = db.execute(
        visible_conversations_query(family_id=family_id, actor_email=actor_email or "", actor_person_id=actor_person_id).order_by(Conversation.updated_at.desc())
    ).scalars()
    return ConversationListResponse(items=[ConversationResponse.model_validate(serialize_conversation(db, row, include_messages=False)) for row in conversations])


@router.post("/families/{family_id}/conversations", response_model=ConversationResponse, status_code=201)
def create_conversation(
    family_id: int,
    payload: ConversationCreateRequest,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
):
    actor_person_id, actor_display_name, _, people = _actor_context(family_id=family_id, actor_email=actor_email)
    if payload.kind == "assistant" and len(payload.assistant_ids) != 1:
        raise_api_error(400, "assistant_count_invalid", "assistant conversations require exactly one top-level assistant")
    conversation = Conversation(
        family_id=family_id,
        kind=payload.kind,
        title=(payload.title or "").strip() or None,
        slug=None,
        visibility_scope=payload.visibility_scope,
        space_type=payload.space_type,
        linked_records_json=payload.linked_records,
        created_by=actor_email or "",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(conversation)
    db.flush()
    db.add(
        ConversationParticipant(
            conversation_id=conversation.conversation_id,
            family_id=family_id,
            participant_kind="human",
            actor_email=actor_email,
            person_id=actor_person_id,
            display_name=actor_display_name,
            role="owner",
        )
    )
    for participant in payload.human_participants:
        if participant.actor_email == actor_email or participant.person_id == actor_person_id:
            continue
        db.add(
            ConversationParticipant(
                conversation_id=conversation.conversation_id,
                family_id=family_id,
                participant_kind="human",
                actor_email=participant.actor_email,
                person_id=participant.person_id,
                display_name=participant.display_name,
                role=participant.role,
            )
        )
    assistant_participants: list[ConversationParticipant] = []
    for assistant_id in payload.assistant_ids:
        participant = ConversationParticipant(
            conversation_id=conversation.conversation_id,
            family_id=family_id,
            participant_kind="top_level_ai",
            display_name=assistant_label(assistant_id),
            top_level_assistant=assistant_id,
            assistant_mode="active" if payload.kind == "assistant" else "passive",
            role="assistant",
        )
        db.add(participant)
        assistant_participants.append(participant)
    db.flush()
    if assistant_participants:
        primary = next((item for item in assistant_participants if item.top_level_assistant == payload.primary_assistant), assistant_participants[0])
        conversation.primary_assistant_id = primary.participant_id
        if payload.kind == "family":
            conversation.kind = "hybrid"
    if payload.kind == "assistant" and not assistant_participants:
        raise_api_error(400, "assistant_required", "assistant conversations require one assistant")
    add_message_with_blocks(
        db,
        conversation=conversation,
        sender_kind="system",
        sender_label="System",
        sender_participant_id=None,
        body_text=f"{conversation.title or 'Conversation'} is ready.",
        metadata={"seed": True},
    )
    db.commit()
    db.refresh(conversation)
    return ConversationResponse.model_validate(serialize_conversation(db, conversation))


@router.get("/families/{family_id}/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    family_id: int,
    conversation_id: str,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
):
    actor_person_id, _, _, _ = _actor_context(family_id=family_id, actor_email=actor_email)
    conversation = ensure_conversation_visible(
        db,
        family_id=family_id,
        conversation_id=conversation_id,
        actor_email=actor_email or "",
        actor_person_id=actor_person_id,
    )
    return ConversationResponse.model_validate(serialize_conversation(db, conversation))


@router.post("/families/{family_id}/conversations/{conversation_id}/attachments", response_model=dict)
async def upload_attachment(
    family_id: int,
    conversation_id: str,
    file: UploadFile = File(...),
    preview_url: str | None = Form(default=None),
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
):
    actor_person_id, _, _, _ = _actor_context(family_id=family_id, actor_email=actor_email)
    conversation = ensure_conversation_visible(
        db,
        family_id=family_id,
        conversation_id=conversation_id,
        actor_email=actor_email or "",
        actor_person_id=actor_person_id,
    )
    storage_path, size_bytes = save_upload(file=file, family_id=family_id, conversation_id=conversation.conversation_id)
    row = Attachment(
        conversation_id=conversation.conversation_id,
        family_id=family_id,
        file_name=file.filename or Path(storage_path).name,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=size_bytes,
        storage_path=storage_path,
        preview_url=preview_url,
        uploaded_by=actor_email or "",
    )
    db.add(row)
    conversation.updated_at = utcnow()
    db.commit()
    return {"attachment": {"attachment_id": row.attachment_id, "file_name": row.file_name, "content_type": row.content_type, "size_bytes": row.size_bytes, "storage_path": row.storage_path, "preview_url": row.preview_url, "created_at": row.created_at}}


@router.post("/families/{family_id}/conversations/{conversation_id}/messages", response_model=ConversationResponse)
async def create_message(
    family_id: int,
    conversation_id: str,
    payload: MessageCreateRequest,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
):
    actor_person_id, actor_display_name, _, _ = _actor_context(family_id=family_id, actor_email=actor_email)
    conversation = ensure_conversation_visible(
        db,
        family_id=family_id,
        conversation_id=conversation_id,
        actor_email=actor_email or "",
        actor_person_id=actor_person_id,
    )
    participants = get_active_participants(db, conversation.conversation_id)
    human_participant = _find_human_participant(participants, actor_email=actor_email or "", actor_person_id=actor_person_id)
    if human_participant is None:
        raise_api_error(403, "conversation_access_denied", "conversation is not writable by this actor")
    attachments = []
    for attachment_id in payload.attachment_ids:
        row = db.get(Attachment, attachment_id)
        if row and row.conversation_id == conversation.conversation_id:
            attachments.append(row)
    body_text = f"{payload.quick_action_prefix.strip()} {payload.body_text}".strip() if payload.quick_action_prefix else payload.body_text.strip()
    user_message = add_message_with_blocks(
        db,
        conversation=conversation,
        sender_kind="human",
        sender_label=human_participant.display_name or actor_display_name,
        sender_participant_id=human_participant.participant_id,
        body_text=body_text,
        reply_to_message_id=payload.reply_to_message_id,
        metadata=payload.metadata,
        attachments=attachments,
    )
    db.commit()
    await realtime_manager.broadcast(
        family_id=family_id,
        conversation_id=conversation.conversation_id,
        event={"type": "message.created", "message_id": user_message.message_id, "sender": user_message.sender_label},
    )
    db.refresh(conversation)
    participants = get_active_participants(db, conversation.conversation_id)
    selected_assistant = select_assistant_for_message(
        conversation=conversation,
        participants=participants,
        body_text=body_text,
        explicit_assistant_id=payload.assistant_id,
        invoke_assistant=payload.invoke_assistant,
    )
    if not selected_assistant:
        return ConversationResponse.model_validate(serialize_conversation(db, conversation))

    run = AgentRun(
        conversation_id=conversation.conversation_id,
        family_id=family_id,
        trigger_message_id=user_message.message_id,
        top_level_assistant=selected_assistant,
        status="running",
        provider="gateway",
        request_json={"body_text": body_text, "assistant_id": selected_assistant},
        response_json={},
        started_at=utcnow(),
    )
    db.add(run)
    db.flush()
    inferred = infer_domain_agents(body_text)
    activities: list[DomainActivity] = []
    for agent_name, summary in inferred:
        activity = DomainActivity(
            conversation_id=conversation.conversation_id,
            family_id=family_id,
            run_id=run.run_id,
            message_id=user_message.message_id,
            agent_name=agent_name,
            state="running",
            summary=summary,
            detail_json={"trigger_message_id": user_message.message_id},
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(activity)
        activities.append(activity)
    db.commit()
    for activity in activities:
        await realtime_manager.broadcast(
            family_id=family_id,
            conversation_id=conversation.conversation_id,
            event={"type": "domain_activity.updated", "activity_id": activity.activity_id, "agent_name": activity.agent_name, "state": activity.state},
        )
    recent_messages = get_messages(db, conversation.conversation_id)
    summaries = list(
        db.execute(
            select(ConversationSummary)
            .where(ConversationSummary.conversation_id == conversation.conversation_id)
            .order_by(ConversationSummary.created_at.asc())
        ).scalars()
    )
    transport_message = build_transport_message(
        conversation=conversation,
        participants=participants,
        actor_label=human_participant.display_name or actor_display_name,
        user_text=body_text,
        summaries=summaries,
        recent_messages=recent_messages,
        targeted_assistant=selected_assistant,
    )
    try:
        result = runtime_adapter.run_turn(
            assistant_id=selected_assistant,
            conversation_id=conversation.conversation_id,
            transport_message=transport_message,
        )
    except Exception as exc:
        run.status = "failed"
        run.response_json = {"error": str(exc)}
        run.completed_at = utcnow()
        for activity in activities:
            activity.state = "failed"
            activity.updated_at = utcnow()
        add_message_with_blocks(
            db,
            conversation=conversation,
            sender_kind="system",
            sender_label="System",
            sender_participant_id=None,
            body_text=f"{assistant_label(selected_assistant)} could not finish this request.",
            blocks=[
                {
                    "block_type": "agent_activity",
                    "text_content": None,
                    "data": {
                        "assistant_id": selected_assistant,
                        "run_id": run.run_id,
                        "state": "failed",
                        "summary": f"{assistant_label(selected_assistant)} could not finish this request.",
                    },
                }
            ],
        )
        db.commit()
        await realtime_manager.broadcast(
            family_id=family_id,
            conversation_id=conversation.conversation_id,
            event={"type": "assistant.run.failed", "run_id": run.run_id, "assistant_id": selected_assistant},
        )
        return ConversationResponse.model_validate(serialize_conversation(db, conversation))

    run.status = "completed"
    run.response_json = result["raw"]
    run.completed_at = utcnow()
    for activity in activities:
        activity.state = "completed"
        activity.updated_at = utcnow()
    assistant_participant = next(
        (item for item in participants if item.top_level_assistant == selected_assistant and item.removed_at is None),
        None,
    )
    add_message_with_blocks(
        db,
        conversation=conversation,
        sender_kind="assistant",
        sender_label=assistant_label(selected_assistant),
        sender_participant_id=assistant_participant.participant_id if assistant_participant else None,
        body_text=result["assistant_text"],
        top_level_assistant=selected_assistant,
        metadata={"run_id": run.run_id, "provider": result["provider"]},
        blocks=[{"block_type": "markdown", "text_content": result["assistant_text"], "data": {"run_id": run.run_id}}],
    )
    db.commit()
    await realtime_manager.broadcast(
        family_id=family_id,
        conversation_id=conversation.conversation_id,
        event={"type": "assistant.run.completed", "run_id": run.run_id, "assistant_id": selected_assistant},
    )
    return ConversationResponse.model_validate(serialize_conversation(db, conversation))


@router.post("/families/{family_id}/conversations/{conversation_id}/participants/assistants", response_model=ConversationResponse)
def invite_assistant(
    family_id: int,
    conversation_id: str,
    payload: AssistantInviteRequest,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
):
    actor_person_id, _, _, _ = _actor_context(family_id=family_id, actor_email=actor_email)
    conversation = ensure_conversation_visible(
        db,
        family_id=family_id,
        conversation_id=conversation_id,
        actor_email=actor_email or "",
        actor_person_id=actor_person_id,
    )
    existing = next(
        (
            item
            for item in get_active_participants(db, conversation.conversation_id)
            if item.top_level_assistant == payload.assistant_id
        ),
        None,
    )
    if existing is None:
        existing = ConversationParticipant(
            conversation_id=conversation.conversation_id,
            family_id=family_id,
            participant_kind="top_level_ai",
            display_name=assistant_label(payload.assistant_id),
            top_level_assistant=payload.assistant_id,
            assistant_mode=payload.assistant_mode,
            role="assistant",
        )
        db.add(existing)
        db.flush()
    else:
        existing.assistant_mode = payload.assistant_mode
        existing.removed_at = None
    if conversation.kind == "family":
        conversation.kind = "hybrid"
    if payload.set_primary or conversation.primary_assistant_id is None:
        conversation.primary_assistant_id = existing.participant_id
    add_message_with_blocks(
        db,
        conversation=conversation,
        sender_kind="system",
        sender_label="System",
        sender_participant_id=None,
        body_text=f"{assistant_label(payload.assistant_id)} joined the conversation.",
        blocks=[{"block_type": "agent_activity", "text_content": None, "data": {"assistant_id": payload.assistant_id, "state": "joined", "summary": f"{assistant_label(payload.assistant_id)} joined the conversation."}}],
    )
    db.commit()
    return ConversationResponse.model_validate(serialize_conversation(db, conversation))


@router.delete("/families/{family_id}/conversations/{conversation_id}/participants/{participant_id}", response_model=ConversationResponse)
def remove_participant(
    family_id: int,
    conversation_id: str,
    participant_id: str,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
):
    actor_person_id, _, _, _ = _actor_context(family_id=family_id, actor_email=actor_email)
    conversation = ensure_conversation_visible(
        db,
        family_id=family_id,
        conversation_id=conversation_id,
        actor_email=actor_email or "",
        actor_person_id=actor_person_id,
    )
    participant = db.get(ConversationParticipant, participant_id)
    if participant is None or participant.conversation_id != conversation.conversation_id:
        raise_api_error(404, "participant_not_found", "participant not found", {"participant_id": participant_id})
    participant.removed_at = utcnow()
    if conversation.primary_assistant_id == participant.participant_id:
        remaining_assistant = next(
            (
                item
                for item in get_active_participants(db, conversation.conversation_id)
                if item.participant_id != participant.participant_id and item.participant_kind == "top_level_ai"
            ),
            None,
        )
        conversation.primary_assistant_id = remaining_assistant.participant_id if remaining_assistant else None
    if not any(item.participant_kind == "top_level_ai" and item.participant_id != participant.participant_id and item.removed_at is None for item in get_active_participants(db, conversation.conversation_id)):
        if conversation.kind == "hybrid":
            conversation.kind = "family"
    add_message_with_blocks(
        db,
        conversation=conversation,
        sender_kind="system",
        sender_label="System",
        sender_participant_id=None,
        body_text=f"{participant.display_name} left the conversation.",
        blocks=[{"block_type": "agent_activity", "text_content": None, "data": {"participant_id": participant.participant_id, "state": "removed", "summary": f"{participant.display_name} left the conversation."}}],
    )
    db.commit()
    return ConversationResponse.model_validate(serialize_conversation(db, conversation))


@router.post("/families/{family_id}/conversations/{conversation_id}/summaries", response_model=ConversationResponse)
def create_summary(
    family_id: int,
    conversation_id: str,
    payload: SummaryCreateRequest,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
):
    actor_person_id, _, _, _ = _actor_context(family_id=family_id, actor_email=actor_email)
    conversation = ensure_conversation_visible(
        db,
        family_id=family_id,
        conversation_id=conversation_id,
        actor_email=actor_email or "",
        actor_person_id=actor_person_id,
    )
    messages = get_messages(db, conversation.conversation_id)
    if payload.message_ids:
        messages = [message for message in messages if message.message_id in set(payload.message_ids)]
    summary, decisions, open_questions, files = summarize_messages(messages)
    record = ConversationSummary(
        conversation_id=conversation.conversation_id,
        family_id=family_id,
        summary_type="on_demand",
        summary=summary,
        decisions_json=decisions,
        open_questions_json=open_questions,
        referenced_files_json=files,
        created_by=actor_email or "",
        created_at=utcnow(),
    )
    db.add(record)
    conversation.latest_summary = summary
    add_message_with_blocks(
        db,
        conversation=conversation,
        sender_kind="system",
        sender_label="System",
        sender_participant_id=None,
        body_text=summary,
        blocks=[{"block_type": "summary_card", "text_content": summary, "data": {"decisions": decisions, "open_questions": open_questions, "referenced_files": files}}],
    )
    db.commit()
    return ConversationResponse.model_validate(serialize_conversation(db, conversation))


@router.post("/families/{family_id}/conversations/{conversation_id}/convert", response_model=ActionMutationResponse)
def convert_conversation(
    family_id: int,
    conversation_id: str,
    payload: ConvertRequest,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
):
    actor_person_id, _, _, _ = _actor_context(family_id=family_id, actor_email=actor_email)
    conversation = ensure_conversation_visible(
        db,
        family_id=family_id,
        conversation_id=conversation_id,
        actor_email=actor_email or "",
        actor_person_id=actor_person_id,
    )
    messages = get_messages(db, conversation.conversation_id)
    selected = [message for message in messages if not payload.message_ids or message.message_id in set(payload.message_ids)]
    summary, decisions, open_questions, files = summarize_messages(selected)
    target_title = payload.title or f"Convert chat to {payload.target}"
    seed_message = add_message_with_blocks(
        db,
        conversation=conversation,
        sender_kind="system",
        sender_label="System",
        sender_participant_id=None,
        body_text=f"Drafted a {payload.target} proposal from this conversation.",
        blocks=[{"block_type": "approval_card", "text_content": None, "data": {"target": payload.target, "status": "proposed", "summary": summary}}],
    )
    proposal = ActionProposal(
        conversation_id=conversation.conversation_id,
        family_id=family_id,
        source_message_id=seed_message.message_id,
        source_conversation_id=conversation.conversation_id,
        action_type=f"convert:{payload.target}",
        title=target_title,
        summary=summary,
        status="proposed",
        request_json={"target": payload.target, "message_ids": payload.message_ids, "decisions": decisions, "open_questions": open_questions, "referenced_files": files},
        result_json={},
        created_by=actor_email or "",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(proposal)
    db.commit()
    return ActionMutationResponse(
        proposal=serialize_conversation(db, conversation)["action_proposals"][0],  # type: ignore[arg-type]
        message=serialize_conversation(db, conversation)["messages"][-1],  # type: ignore[arg-type]
    )


def _mutate_action(
    *,
    family_id: int,
    action_id: str,
    actor_email: str | None,
    db: Session,
    next_status: str,
) -> tuple[Conversation, ActionProposal, Message]:
    proposal = db.get(ActionProposal, action_id)
    if proposal is None or proposal.family_id != family_id:
        raise_api_error(404, "proposal_not_found", "action proposal not found", {"action_id": action_id})
    actor_person_id, _, _, _ = _actor_context(family_id=family_id, actor_email=actor_email)
    conversation = ensure_conversation_visible(
        db,
        family_id=family_id,
        conversation_id=proposal.conversation_id,
        actor_email=actor_email or "",
        actor_person_id=actor_person_id,
    )
    proposal.status = next_status
    proposal.updated_at = utcnow()
    if next_status == "committed":
        proposal.result_json = {
            "status": "committed",
            "source_conversation_id": proposal.source_conversation_id,
            "source_message_id": proposal.source_message_id,
            "canonical_event_ids": [],
        }
    message = add_message_with_blocks(
        db,
        conversation=conversation,
        sender_kind="system",
        sender_label="System",
        sender_participant_id=None,
        body_text=f"{proposal.title} is now {next_status}.",
        blocks=[{"block_type": "approval_card", "text_content": None, "data": {"action_id": proposal.action_id, "status": next_status, "summary": proposal.summary}}],
    )
    db.commit()
    db.refresh(proposal)
    return conversation, proposal, message


@router.post("/families/{family_id}/actions/{action_id}/confirm", response_model=ActionMutationResponse)
def confirm_action(
    family_id: int,
    action_id: str,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
):
    conversation, proposal, message = _mutate_action(family_id=family_id, action_id=action_id, actor_email=actor_email, db=db, next_status="confirmed")
    serialized = serialize_conversation(db, conversation)
    proposal_payload = next(item for item in serialized["action_proposals"] if item["action_id"] == proposal.action_id)
    message_payload = next(item for item in serialized["messages"] if item["message_id"] == message.message_id)
    return ActionMutationResponse(proposal=proposal_payload, message=message_payload)


@router.post("/families/{family_id}/actions/{action_id}/commit", response_model=ActionMutationResponse)
def commit_action(
    family_id: int,
    action_id: str,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
):
    conversation, proposal, message = _mutate_action(family_id=family_id, action_id=action_id, actor_email=actor_email, db=db, next_status="committed")
    serialized = serialize_conversation(db, conversation)
    proposal_payload = next(item for item in serialized["action_proposals"] if item["action_id"] == proposal.action_id)
    message_payload = next(item for item in serialized["messages"] if item["message_id"] == message.message_id)
    return ActionMutationResponse(proposal=proposal_payload, message=message_payload)


@router.post("/families/{family_id}/actions/{action_id}/cancel", response_model=ActionMutationResponse)
def cancel_action(
    family_id: int,
    action_id: str,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
):
    conversation, proposal, message = _mutate_action(family_id=family_id, action_id=action_id, actor_email=actor_email, db=db, next_status="canceled")
    serialized = serialize_conversation(db, conversation)
    proposal_payload = next(item for item in serialized["action_proposals"] if item["action_id"] == proposal.action_id)
    message_payload = next(item for item in serialized["messages"] if item["message_id"] == message.message_id)
    return ActionMutationResponse(proposal=proposal_payload, message=message_payload)


@router.post("/families/{family_id}/messages/{message_id}/share", response_model=ConversationResponse)
def share_message(
    family_id: int,
    message_id: str,
    payload: ShareRequest,
    db: Session = Depends(get_db),
    actor_email: str | None = Depends(_actor_email),
):
    message = db.get(Message, message_id)
    if message is None or message.family_id != family_id:
        raise_api_error(404, "message_not_found", "message not found", {"message_id": message_id})
    actor_person_id, _, _, _ = _actor_context(family_id=family_id, actor_email=actor_email)
    source_conversation = ensure_conversation_visible(
        db,
        family_id=family_id,
        conversation_id=message.conversation_id,
        actor_email=actor_email or "",
        actor_person_id=actor_person_id,
    )
    target_conversation = ensure_conversation_visible(
        db,
        family_id=family_id,
        conversation_id=payload.target_conversation_id,
        actor_email=actor_email or "",
        actor_person_id=actor_person_id,
    )
    add_message_with_blocks(
        db,
        conversation=target_conversation,
        sender_kind="system",
        sender_label="System",
        sender_participant_id=None,
        body_text=payload.note or f"Shared from {source_conversation.title or 'another chat'}: {(message.body_text or '').strip()}",
        blocks=[{"block_type": "summary_card", "text_content": message.body_text or "", "data": {"shared_from_message_id": message.message_id, "shared_from_conversation_id": source_conversation.conversation_id, "note": payload.note}}],
    )
    db.add(
        ShareEvent(
            family_id=family_id,
            source_conversation_id=source_conversation.conversation_id,
            source_message_id=message.message_id,
            target_conversation_id=target_conversation.conversation_id,
            created_by=actor_email or "",
            created_at=utcnow(),
        )
    )
    db.commit()
    return ConversationResponse.model_validate(serialize_conversation(db, target_conversation))


@router.websocket("/families/{family_id}/realtime/ws")
async def realtime_socket(
    websocket: WebSocket,
    family_id: int,
    conversation_id: str,
):
    actor_email = websocket.headers.get("x-forwarded-user") or websocket.headers.get("x-dev-user") or websocket.query_params.get("actor")
    if not actor_email:
        await websocket.close(code=4401)
        return
    try:
        actor_person_id, _, _, _ = _actor_context(family_id=family_id, actor_email=actor_email.strip().lower())
    except Exception:
        await websocket.close(code=4403)
        return
    db = SessionLocal()
    try:
        ensure_conversation_visible(
            db,
            family_id=family_id,
            conversation_id=conversation_id,
            actor_email=actor_email.strip().lower(),
            actor_person_id=actor_person_id,
        )
    except Exception:
        db.close()
        await websocket.close(code=4403)
        return
    db.close()
    await realtime_manager.connect(family_id=family_id, conversation_id=conversation_id, websocket=websocket)
    try:
        while True:
            message = await websocket.receive_json()
            event_type = str(message.get("type") or "")
            if event_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif event_type == "typing":
                await realtime_manager.broadcast(
                    family_id=family_id,
                    conversation_id=conversation_id,
                    event={"type": "typing", "conversation_id": conversation_id, "actor": actor_email},
                )
    except WebSocketDisconnect:
        await realtime_manager.disconnect(family_id=family_id, conversation_id=conversation_id, websocket=websocket)
