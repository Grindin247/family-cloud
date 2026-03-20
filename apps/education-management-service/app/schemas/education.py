from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OrmResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LearnerCreate(BaseModel):
    family_id: int = Field(ge=1)
    learner_id: UUID
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    birthdate: date | None = None
    timezone: str | None = Field(default=None, max_length=64)
    status: str = Field(default="active", min_length=1, max_length=32)


class LearnerResponse(OrmResponse):
    learner_id: UUID
    family_id: int
    display_name: str
    birthdate: date | None = None
    timezone: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class DomainResponse(OrmResponse):
    domain_id: UUID
    code: str
    name: str
    description: str | None = None
    created_at: datetime


class SkillResponse(OrmResponse):
    skill_id: UUID
    domain_id: UUID
    code: str
    name: str
    description: str | None = None
    parent_skill_id: UUID | None = None
    created_at: datetime


class GoalCreate(BaseModel):
    family_id: int = Field(ge=1)
    learner_id: UUID
    domain_id: UUID
    skill_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: str = Field(default="active", min_length=1, max_length=32)
    start_date: date | None = None
    target_date: date | None = None
    target_metric_type: str | None = Field(default=None, max_length=64)
    target_metric_value: float | None = None


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = Field(default=None, min_length=1, max_length=32)
    start_date: date | None = None
    target_date: date | None = None
    target_metric_type: str | None = Field(default=None, max_length=64)
    target_metric_value: float | None = None


class GoalResponse(OrmResponse):
    goal_id: UUID
    family_id: int
    learner_id: UUID
    domain_id: UUID
    skill_id: UUID | None = None
    title: str
    description: str | None = None
    status: str
    start_date: date | None = None
    target_date: date | None = None
    target_metric_type: str | None = None
    target_metric_value: float | None = None
    created_at: datetime
    updated_at: datetime


class ActivityCreate(BaseModel):
    family_id: int = Field(ge=1)
    learner_id: UUID
    domain_id: UUID | None = None
    skill_id: UUID | None = None
    activity_type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    occurred_at: datetime
    duration_seconds: int | None = Field(default=None, ge=0)
    source: str = Field(default="education-agent", min_length=1, max_length=64)
    source_ref: str | None = Field(default=None, max_length=255)
    created_by: str | None = Field(default=None, max_length=255)
    source_session_id: str | None = Field(default=None, max_length=255)


class ActivityResponse(OrmResponse):
    activity_id: UUID
    family_id: int
    learner_id: UUID
    domain_id: UUID | None = None
    skill_id: UUID | None = None
    activity_type: str
    title: str
    description: str | None = None
    occurred_at: datetime
    duration_seconds: int | None = None
    source: str
    source_ref: str | None = None
    created_by: str
    source_session_id: str | None = None
    created_at: datetime


class AssignmentCreate(BaseModel):
    family_id: int = Field(ge=1)
    learner_id: UUID
    domain_id: UUID | None = None
    skill_id: UUID | None = None
    activity_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    assigned_at: datetime | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    source: str = Field(default="education-agent", min_length=1, max_length=64)
    source_ref: str | None = Field(default=None, max_length=255)
    status: str = Field(default="assigned", min_length=1, max_length=32)
    max_score: float | None = None
    rubric_json: dict[str, Any] | None = None


class AssignmentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    assigned_at: datetime | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    source_ref: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, min_length=1, max_length=32)
    max_score: float | None = None
    rubric_json: dict[str, Any] | None = None


class AssignmentResponse(OrmResponse):
    assignment_id: UUID
    family_id: int
    learner_id: UUID
    domain_id: UUID | None = None
    skill_id: UUID | None = None
    activity_id: UUID | None = None
    title: str
    description: str | None = None
    assigned_at: datetime | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    source: str
    source_ref: str | None = None
    status: str
    max_score: float | None = None
    rubric_json: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class AssessmentCreate(BaseModel):
    family_id: int = Field(ge=1)
    learner_id: UUID
    domain_id: UUID | None = None
    skill_id: UUID | None = None
    assignment_id: UUID | None = None
    activity_id: UUID | None = None
    assessment_type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    occurred_at: datetime
    score: float | None = None
    max_score: float | None = None
    percent: float | None = None
    confidence_self_report: float | None = None
    rubric_json: dict[str, Any] | None = None
    graded_by: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class AssessmentResponse(OrmResponse):
    assessment_id: UUID
    family_id: int
    learner_id: UUID
    domain_id: UUID | None = None
    skill_id: UUID | None = None
    assignment_id: UUID | None = None
    activity_id: UUID | None = None
    assessment_type: str
    title: str
    occurred_at: datetime
    score: float | None = None
    max_score: float | None = None
    percent: float | None = None
    confidence_self_report: float | None = None
    rubric_json: dict[str, Any] | None = None
    graded_by: str
    notes: str | None = None
    created_at: datetime


class PracticeRepetitionCreate(BaseModel):
    family_id: int = Field(ge=1)
    learner_id: UUID
    domain_id: UUID | None = None
    skill_id: UUID | None = None
    topic_text: str | None = None
    occurred_at: datetime
    duration_seconds: int | None = Field(default=None, ge=0)
    attempt_number: int | None = Field(default=None, ge=1)
    performance_score: float | None = None
    difficulty_self_report: float | None = None
    confidence_self_report: float | None = None
    notes: str | None = None


class PracticeRepetitionResponse(OrmResponse):
    repetition_id: UUID
    family_id: int
    learner_id: UUID
    domain_id: UUID | None = None
    skill_id: UUID | None = None
    topic_text: str | None = None
    occurred_at: datetime
    duration_seconds: int | None = None
    attempt_number: int | None = None
    performance_score: float | None = None
    difficulty_self_report: float | None = None
    confidence_self_report: float | None = None
    notes: str | None = None
    created_at: datetime


class JournalCreate(BaseModel):
    family_id: int = Field(ge=1)
    learner_id: UUID
    occurred_at: datetime
    title: str | None = Field(default=None, max_length=255)
    content: str = Field(min_length=1)
    mood_self_report: str | None = Field(default=None, max_length=64)
    effort_self_report: float | None = None


class JournalResponse(OrmResponse):
    journal_id: UUID
    family_id: int
    learner_id: UUID
    occurred_at: datetime
    title: str | None = None
    content: str
    mood_self_report: str | None = None
    effort_self_report: float | None = None
    created_at: datetime


class QuizCreate(BaseModel):
    family_id: int = Field(ge=1)
    learner_id: UUID
    domain_id: UUID | None = None
    skill_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    created_by: str | None = Field(default=None, max_length=255)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    delivery_mode: str = Field(min_length=1, max_length=64)
    source: str = Field(default="education-agent", min_length=1, max_length=64)
    source_ref: str | None = Field(default=None, max_length=255)
    total_items: int | None = None
    total_score: float | None = None
    max_score: float | None = None


class QuizSessionResponse(OrmResponse):
    quiz_id: UUID
    family_id: int
    learner_id: UUID
    domain_id: UUID | None = None
    skill_id: UUID | None = None
    title: str
    created_by: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    delivery_mode: str
    source: str
    source_ref: str | None = None
    total_items: int | None = None
    total_score: float | None = None
    max_score: float | None = None
    created_at: datetime


class QuizItemInput(BaseModel):
    position: int = Field(ge=1)
    prompt_text: str = Field(min_length=1)
    item_type: str = Field(min_length=1, max_length=64)
    correct_answer_json: dict[str, Any] | list[Any] | str | None = None
    rubric_json: dict[str, Any] | None = None
    max_score: float | None = None
    metadata_json: dict[str, Any] | None = None


class QuizItemsCreate(BaseModel):
    family_id: int = Field(ge=1)
    items: list[QuizItemInput] = Field(default_factory=list, min_length=1)


class QuizItemResponse(OrmResponse):
    quiz_item_id: UUID
    family_id: int
    quiz_id: UUID
    position: int
    prompt_text: str
    item_type: str
    correct_answer_json: dict[str, Any] | list[Any] | str | None = None
    rubric_json: dict[str, Any] | None = None
    max_score: float | None = None
    metadata_json: dict[str, Any] | None = None
    created_at: datetime


class QuizResponseInput(BaseModel):
    quiz_item_id: UUID
    response_json: dict[str, Any] | list[Any] | str | None = None
    score: float | None = None
    max_score: float | None = None
    correctness: bool | None = None
    confidence_self_report: float | None = None
    latency_ms: int | None = Field(default=None, ge=0)


class QuizResponsesCreate(BaseModel):
    family_id: int = Field(ge=1)
    learner_id: UUID
    responses: list[QuizResponseInput] = Field(default_factory=list, min_length=1)


class QuizResponseRecord(OrmResponse):
    response_id: UUID
    family_id: int
    quiz_id: UUID
    quiz_item_id: UUID
    learner_id: UUID
    response_json: dict[str, Any] | list[Any] | str | None = None
    score: float | None = None
    max_score: float | None = None
    correctness: bool | None = None
    confidence_self_report: float | None = None
    latency_ms: int | None = None
    created_at: datetime


class QuizDetailResponse(BaseModel):
    session: QuizSessionResponse
    items: list[QuizItemResponse] = Field(default_factory=list)
    responses: list[QuizResponseRecord] = Field(default_factory=list)


class AttachmentCreate(BaseModel):
    family_id: int = Field(ge=1)
    learner_id: UUID
    entity_type: str = Field(min_length=1, max_length=64)
    entity_id: UUID | str
    file_ref: str = Field(min_length=1)
    mime_type: str | None = Field(default=None, max_length=255)


class AttachmentResponse(OrmResponse):
    attachment_id: UUID
    family_id: int
    learner_id: UUID
    entity_type: str
    entity_id: str
    file_ref: str
    mime_type: str | None = None
    created_at: datetime


class ProgressSnapshotResponse(OrmResponse):
    snapshot_id: UUID
    family_id: int
    learner_id: UUID
    domain_id: UUID | None = None
    skill_id: UUID | None = None
    scope_key: str
    as_of_date: date
    activity_count_7d: int
    activity_count_30d: int
    practice_count_7d: int
    practice_count_30d: int
    assessment_count_30d: int
    avg_score_30d: float | None = None
    latest_score: float | None = None
    latest_assessment_at: datetime | None = None
    total_minutes_30d: float | None = None
    created_at: datetime
    updated_at: datetime


class StatsResponse(BaseModel):
    family_id: int
    learner_id: UUID
    domain_id: UUID | None = None
    skill_id: UUID | None = None
    as_of_date: date
    activity_count_7d: int
    activity_count_30d: int
    practice_count_7d: int
    practice_count_30d: int
    assessment_count_30d: int
    avg_score_30d: float | None = None
    latest_score: float | None = None
    latest_assessment_at: datetime | None = None
    total_minutes_30d: float | None = None
    assignment_open_count: int
    assignment_completed_count: int
    journal_count_30d: int
    quiz_session_count_30d: int
    days_since_last_practice: int | None = None


class EducationSummaryResponse(BaseModel):
    learner: LearnerResponse
    active_goals: list[GoalResponse] = Field(default_factory=list)
    recent_activities: list[ActivityResponse] = Field(default_factory=list)
    recent_assignments: list[AssignmentResponse] = Field(default_factory=list)
    recent_assessments: list[AssessmentResponse] = Field(default_factory=list)
    recent_practice_repetitions: list[PracticeRepetitionResponse] = Field(default_factory=list)
    recent_quiz_sessions: list[QuizSessionResponse] = Field(default_factory=list)
    latest_snapshots: list[ProgressSnapshotResponse] = Field(default_factory=list)
    stats: StatsResponse
