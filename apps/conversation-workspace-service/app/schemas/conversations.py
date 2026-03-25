from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ConversationKind = Literal["assistant", "family", "hybrid"]
ParticipantKind = Literal["human", "top_level_ai"]
TopLevelAssistant = Literal["caleb", "amelia"]
AssistantMode = Literal["passive", "active"]
SenderKind = Literal["human", "assistant", "system", "agent"]
DomainActivityState = Literal["queued", "running", "waiting", "completed", "failed"]
MessageBlockType = Literal["markdown", "task_card", "note_card", "plan_card", "file_card", "event_card", "approval_card", "summary_card", "agent_activity"]


class AssistantDefinition(BaseModel):
    assistant_id: TopLevelAssistant
    label: str
    description: str


class ViewerMeResponse(BaseModel):
    authenticated: bool
    email: str | None = None
    memberships: list[dict[str, Any]] = Field(default_factory=list)


class ViewerContextResponse(BaseModel):
    family_id: int
    family_slug: str
    actor_email: str
    actor_person_id: str
    target_person_id: str
    is_family_admin: bool
    assistants: list[AssistantDefinition] = Field(default_factory=list)
    persons: list[dict[str, Any]] = Field(default_factory=list)


class ParticipantSeed(BaseModel):
    person_id: str | None = None
    actor_email: str | None = None
    display_name: str
    role: str = "member"


class ConversationParticipantResponse(BaseModel):
    participant_id: str
    participant_kind: ParticipantKind
    actor_email: str | None = None
    person_id: str | None = None
    display_name: str
    top_level_assistant: TopLevelAssistant | None = None
    assistant_mode: AssistantMode | None = None
    role: str
    joined_at: datetime


class MessageBlockResponse(BaseModel):
    block_id: str
    block_type: MessageBlockType
    text_content: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    position: int


class AttachmentResponse(BaseModel):
    attachment_id: str
    file_name: str
    content_type: str
    size_bytes: int
    storage_path: str
    preview_url: str | None = None
    created_at: datetime


class MessageResponse(BaseModel):
    message_id: str
    sender_kind: SenderKind
    sender_label: str
    top_level_assistant: TopLevelAssistant | None = None
    body_text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    reply_to_message_id: str | None = None
    created_at: datetime
    blocks: list[MessageBlockResponse] = Field(default_factory=list)
    attachments: list[AttachmentResponse] = Field(default_factory=list)


class ConversationSummaryResponse(BaseModel):
    summary_id: str
    summary_type: str
    summary: str
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    referenced_files: list[str] = Field(default_factory=list)
    created_by: str
    created_at: datetime


class DomainActivityResponse(BaseModel):
    activity_id: str
    agent_name: str
    state: DomainActivityState
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    message_id: str | None = None
    updated_at: datetime


class ActionProposalResponse(BaseModel):
    action_id: str
    action_type: str
    title: str
    summary: str
    status: str
    request: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    source_conversation_id: str
    source_message_id: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class ConversationResponse(BaseModel):
    conversation_id: str
    family_id: int
    kind: ConversationKind
    title: str
    visibility_scope: str
    space_type: str
    linked_records: list[dict[str, Any]] = Field(default_factory=list)
    primary_assistant_id: str | None = None
    latest_summary: str | None = None
    latest_message_preview: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    participants: list[ConversationParticipantResponse] = Field(default_factory=list)
    messages: list[MessageResponse] = Field(default_factory=list)
    summaries: list[ConversationSummaryResponse] = Field(default_factory=list)
    domain_activity: list[DomainActivityResponse] = Field(default_factory=list)
    action_proposals: list[ActionProposalResponse] = Field(default_factory=list)


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse] = Field(default_factory=list)


class ConversationCreateRequest(BaseModel):
    kind: ConversationKind
    title: str | None = None
    visibility_scope: str = "participants"
    space_type: str = "none"
    linked_records: list[dict[str, Any]] = Field(default_factory=list)
    assistant_ids: list[TopLevelAssistant] = Field(default_factory=list)
    human_participants: list[ParticipantSeed] = Field(default_factory=list)
    primary_assistant: TopLevelAssistant | None = None


class MessageCreateRequest(BaseModel):
    body_text: str = Field(min_length=1)
    reply_to_message_id: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)
    invoke_assistant: bool = False
    assistant_id: TopLevelAssistant | None = None
    quick_action_prefix: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SummaryCreateRequest(BaseModel):
    scope: str = "latest"
    message_ids: list[str] = Field(default_factory=list)


class ConvertRequest(BaseModel):
    target: Literal["tasks", "note", "plan"]
    message_ids: list[str] = Field(default_factory=list)
    title: str | None = None


class ShareRequest(BaseModel):
    target_conversation_id: str
    note: str | None = None


class AssistantInviteRequest(BaseModel):
    assistant_id: TopLevelAssistant
    assistant_mode: AssistantMode = "passive"
    set_primary: bool = False


class ActionMutationResponse(BaseModel):
    proposal: ActionProposalResponse
    message: MessageResponse
