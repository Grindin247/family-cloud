from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


QUESTION_STATUS_PATTERN = "^(pending|asked|answered_partial|resolved|expired|dismissed)$"
QUESTION_URGENCY_PATTERN = "^(low|medium|high|critical)$"


class QuestionResponse(BaseModel):
    id: str
    family_id: int
    domain: str
    source_agent: str
    topic: str
    category: str
    topic_type: str
    summary: str
    prompt: str
    urgency: str
    status: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    due_at: datetime | None = None
    last_asked_at: datetime | None = None
    answered_at: datetime | None = None
    answer_text: str | None = None
    answer_sufficiency_state: str
    asked_count: int
    last_delivery_channel: str | None = None
    last_delivery_agent: str | None = None
    current_claim: dict[str, Any] | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    dedupe_key: str


class QuestionEventResponse(BaseModel):
    id: int
    question_id: str
    family_id: int
    actor: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class QuestionDeliveryAttemptResponse(BaseModel):
    id: int
    question_id: str
    family_id: int
    claim_token: str | None = None
    agent_id: str
    channel: str
    sent_at: datetime
    responded_at: datetime | None = None
    outcome: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class QuestionMutationResponse(BaseModel):
    question: QuestionResponse | None = None
    event: QuestionEventResponse | None = None
    attempt: QuestionDeliveryAttemptResponse | None = None
    suppressed: bool = False
    suppression_reason: str | None = None


class CreateQuestionRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=64)
    source_agent: str = Field(min_length=1, max_length=128)
    topic: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=64)
    topic_type: str | None = Field(default=None, max_length=64)
    summary: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    urgency: str = Field(default="medium", pattern=QUESTION_URGENCY_PATTERN)
    expires_at: datetime | None = None
    due_at: datetime | None = None
    answer_sufficiency_state: str = Field(default="unknown", max_length=32)
    context: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str = Field(min_length=1, max_length=255)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)


class UpdateQuestionRequest(BaseModel):
    topic: str | None = Field(default=None, max_length=255)
    summary: str | None = None
    prompt: str | None = None
    urgency: str | None = Field(default=None, pattern=QUESTION_URGENCY_PATTERN)
    category: str | None = Field(default=None, max_length=64)
    topic_type: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, pattern=QUESTION_STATUS_PATTERN)
    expires_at: datetime | None = None
    due_at: datetime | None = None
    answer_sufficiency_state: str | None = None
    context_patch: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] | None = None


class MarkQuestionAskedRequest(BaseModel):
    delivery_agent: str = Field(min_length=1, max_length=128)
    delivery_channel: str = Field(default="discord_dm", min_length=1, max_length=64)
    claim_token: str | None = None
    delivery_context: dict[str, Any] = Field(default_factory=dict)


class AnswerQuestionRequest(BaseModel):
    answer_text: str = Field(min_length=1)
    status: str = Field(default="resolved", pattern="^(resolved|answered_partial)$")
    answer_sufficiency_state: str | None = None
    resolution_note: str | None = None
    responded_at: datetime | None = None
    outcome: str = Field(default="responded", max_length=32)
    context_patch: dict[str, Any] = Field(default_factory=dict)


class ResolveQuestionRequest(BaseModel):
    status: str = Field(pattern="^(resolved|expired|dismissed|answered_partial)$")
    resolution_note: str | None = None
    answer_sufficiency_state: str | None = None
    context_patch: dict[str, Any] = Field(default_factory=dict)


class ListQuestionsResponse(BaseModel):
    items: list[QuestionResponse] = Field(default_factory=list)


class QuestionHistoryResponse(BaseModel):
    events: list[QuestionEventResponse] = Field(default_factory=list)
    attempts: list[QuestionDeliveryAttemptResponse] = Field(default_factory=list)


class ClaimNextQuestionRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    channel: str = Field(default="discord_dm", min_length=1, max_length=64)
    lease_seconds: int | None = Field(default=None, ge=60, le=7200)
    allow_merge: bool = True
    force: bool = False
    local_timezone: str | None = None


class ClaimNextQuestionResponse(BaseModel):
    items: list[QuestionResponse] = Field(default_factory=list)
    claim_token: str | None = None
    eligible: bool
    reason: str | None = None


class PurgeQuestionsRequest(BaseModel):
    question_ids: list[str] = Field(default_factory=list)
    domain: str | None = None
    status: str | None = Field(default=None, pattern=QUESTION_STATUS_PATTERN)
    category: str | None = None
    all: bool = False


class PurgeQuestionsResponse(BaseModel):
    deleted: int


class ViewerMembership(BaseModel):
    family_id: int
    family_name: str
    member_id: int
    person_id: str | None = None
    role: str


class QuestionViewerMeResponse(BaseModel):
    authenticated: bool
    email: str | None
    memberships: list[ViewerMembership] = Field(default_factory=list)
