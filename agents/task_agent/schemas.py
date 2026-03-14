from __future__ import annotations

from datetime import datetime
from typing import Any, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


TaskStatus = Literal["executed", "needs_input", "failed"]
IntentMode = Literal["mutate_tasks", "insights_only", "hybrid"]
OperationType = Literal[
    "ensure_list",
    "rename_list",
    "delete_list",
    "archive_list",
    "reparent_list",
    "ensure_team",
    "share_list_with_team",
    "ensure_label",
    "add_label_to_task",
    "set_task_assignees",
    "set_task_progress",
    "set_task_color",
    "set_task_repeat",
    "add_task_attachment",
    "add_task_relation",
    "move_task",
    "create_task",
    "update_task",
    "complete_task",
    "reopen_task",
    "comment_task",
    "delete_task",
    "get_task",
    "get_all_projects",
    "get_all_tasks",
    "noop",
]


class TaskAttachment(BaseModel):
    type: str = Field(default="application/octet-stream")
    name: str = Field(min_length=1)
    url: str | None = None
    bytes_base64: str | None = None


class TaskInvokeRequest(BaseModel):
    message: str = ""
    actor: str = Field(min_length=1)
    family_id: int
    session_id: str | None = None
    attachments: list[TaskAttachment] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlannedOperation(BaseModel):
    type: OperationType
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class TaskActionPlan(BaseModel):
    intent_summary: str
    intent_mode: IntentMode
    operations: list[PlannedOperation] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    missing_info: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ExecutionOperationResult(BaseModel):
    type: OperationType
    payload: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None


class TaskExecution(BaseModel):
    executed_operations: list[ExecutionOperationResult] = Field(default_factory=list)
    failed_operations: list[ExecutionOperationResult] = Field(default_factory=list)


class InsightOverview(BaseModel):
    total_lists: int = 0
    total_open_tasks: int = 0
    total_done_tasks: int = 0
    overdue_tasks: int = 0


class InsightTaskItem(BaseModel):
    task_id: int | None = None
    list_id: int | None = None
    list_name: str = ""
    title: str
    due_date: str | None = None
    done: bool | None = None


class TaskInsights(BaseModel):
    generated_at: datetime
    overview: InsightOverview = Field(default_factory=InsightOverview)
    due_soon: list[InsightTaskItem] = Field(default_factory=list)
    overdue: list[InsightTaskItem] = Field(default_factory=list)
    stale: list[InsightTaskItem] = Field(default_factory=list)
    relevant_tasks: list[InsightTaskItem] = Field(default_factory=list)
    query_topic: str | None = None
    query_terms: list[str] = Field(default_factory=list)
    query_answer: str | None = None
    at_risk_projects: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    all_projects: list[dict[str, Any]] = Field(default_factory=list)
    all_tasks: list[dict[str, Any]] = Field(default_factory=list)


class ProjectIdea(BaseModel):
    title: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str
    tasks: list[str] = Field(default_factory=list)


class TaskAgentResponse(BaseModel):
    schema_version: str = "1.0"
    status: TaskStatus
    mode: Literal["extract", "ops"] = "extract"
    intent: str = ""
    plan: TaskActionPlan | None = None
    execution: TaskExecution = Field(default_factory=TaskExecution)
    executed_operations: list[dict[str, Any]] = Field(default_factory=list)
    failed_operations: list[dict[str, Any]] = Field(default_factory=list)
    created_task_ids: list[int] = Field(default_factory=list)
    updated_task_ids: list[int] = Field(default_factory=list)
    moved_task_ids: list[int] = Field(default_factory=list)
    created_list_ids: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    insights: TaskInsights | None = None
    project_ideas: list[ProjectIdea] = Field(default_factory=list)
    explanation: str = ""
    followups: list[str] = Field(default_factory=list)
    artifacts: dict[str, list[int | str]] = Field(default_factory=dict)
    raw_tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    session_id: str | None = None


class HealthStatus(BaseModel):
    ok: bool
    backend_reachable: bool
    tools_discovered: list[str] = Field(default_factory=list)
    error: str | None = None


class _OpsBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnsureListOp(_OpsBase):
    type: Literal["ensure_list"]
    title: str = Field(min_length=1)
    description: str = ""


class RenameListOp(_OpsBase):
    type: Literal["rename_list"]
    list_id: StrictInt
    title: str = Field(min_length=1)


class MoveTaskOp(_OpsBase):
    type: Literal["move_task"]
    task_id: StrictInt
    list_id: StrictInt | None = None
    list_id_ref: str | None = None

    @model_validator(mode="after")
    def _require_target(self) -> "MoveTaskOp":
        if self.list_id is None and not (self.list_id_ref or "").strip():
            raise ValueError("move_task requires list_id or list_id_ref")
        return self


class CreateTaskOp(_OpsBase):
    type: Literal["create_task"]
    title: str = Field(min_length=1)
    description: str = ""
    due_date: str | None = None
    list_id: StrictInt | None = None
    list_id_ref: str | None = None

    @model_validator(mode="after")
    def _require_target(self) -> "CreateTaskOp":
        if self.list_id is None and not (self.list_id_ref or "").strip():
            raise ValueError("create_task requires list_id or list_id_ref")
        return self


class UpdateTaskOp(_OpsBase):
    type: Literal["update_task"]
    task_id: StrictInt
    patch: dict[str, Any] = Field(default_factory=dict)


class CompleteTaskOp(_OpsBase):
    type: Literal["complete_task"]
    task_id: StrictInt
    done: Literal[True] = True


class DeleteTaskOp(_OpsBase):
    type: Literal["delete_task"]
    task_id: StrictInt


class DeleteListOp(_OpsBase):
    type: Literal["delete_list"]
    list_id: StrictInt


class ArchiveListOp(_OpsBase):
    type: Literal["archive_list"]
    list_id: StrictInt
    archived: bool = True


class GetTassksOp(_OpsBase):
    type: Literal["get_task"]
    task_id: StrictInt


class GetAllProjectsOp(_OpsBase):
    type: Literal["get_all_projects"]


class GetAllTasksOp(_OpsBase):
    type: Literal["get_all_tasks"]


OpsOperation = Annotated[
    EnsureListOp
    | RenameListOp
    | MoveTaskOp
    | CreateTaskOp
    | UpdateTaskOp
    | CompleteTaskOp
    | DeleteTaskOp
    | DeleteListOp
    | ArchiveListOp
    | GetTassksOp
    | GetAllProjectsOp
    | GetAllTasksOp,
    Field(discriminator="type"),
]


class OpsEnvelope(_OpsBase):
    mode: Literal["ops"]
    stop_on_error: bool = False
    confirmation: str | None = None
    operations: list[OpsOperation] = Field(default_factory=list)
