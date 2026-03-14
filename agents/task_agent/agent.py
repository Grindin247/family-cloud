from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import base64
import difflib
import json
import re
from typing import Any
from zoneinfo import ZoneInfo

from agents.common.observability.tracing import new_correlation_id

from .ai import ExtractedTask, TaskAi
from .ops_mode import is_management_command_without_ops, parse_ops_message, strip_control_lines
from .schemas import (
    ArchiveListOp,
    CompleteTaskOp,
    CreateTaskOp,
    DeleteListOp,
    DeleteTaskOp,
    ExecutionOperationResult,
    GetAllProjectsOp,
    GetAllTasksOp,
    GetTassksOp,
    MoveTaskOp,
    OpsEnvelope,
    PlannedOperation,
    ProjectIdea,
    RenameListOp,
    EnsureListOp,
    TaskActionPlan,
    TaskAgentResponse,
    TaskExecution,
    TaskInsights,
    TaskInvokeRequest,
    UpdateTaskOp,
    InsightOverview,
    InsightTaskItem,
)
from .settings import task_settings
from .tools import TaskTools, task_tools


@dataclass
class TaskAgent:
    name: str = "tasks"
    ai: TaskAi | None = None
    tools: TaskTools | None = None

    def run(self, req: TaskInvokeRequest) -> TaskAgentResponse:
        request_id = new_correlation_id()
        tools = self.tools or task_tools()
        actor = req.actor.strip()
        session_id = (req.session_id or "default").strip() or "default"
        ops_parse = parse_ops_message(req.message)
        if ops_parse.triggered:
            if ops_parse.error or ops_parse.envelope is None:
                failed = TaskAgentResponse(
                    status="failed",
                    mode="ops",
                    intent="ops",
                    execution=TaskExecution(),
                    explanation="OPS payload parsing failed.",
                    artifacts={"request_ids": [request_id]},
                    notes=[ops_parse.error or "invalid_ops_payload"],
                    session_id=session_id,
                )
                return self._finalize_contract_response(failed, mode="ops")
            return self._run_ops_mode(
                req=req,
                envelope=ops_parse.envelope,
                tools=tools,
                request_id=request_id,
                session_id=session_id,
            )

        if is_management_command_without_ops(req.message):
            blocked = TaskAgentResponse(
                status="needs_input",
                mode="extract",
                intent="mutate_tasks",
                execution=TaskExecution(),
                explanation="Administrative operation requires explicit OPS mode payload.",
                artifacts={"request_ids": [request_id]},
                followups=["Use OPS mode with JSON payload (`mode\":\"ops\"`) to run admin operations (rename/move/delete/archive/clear)."],
                notes=["management_command_requires_ops_mode"],
                session_id=session_id,
            )
            return self._finalize_contract_response(blocked, mode="extract")

        ai = self.ai or TaskAi()
        capabilities = self._safe_capabilities(tools)
        attachment_text = self._extract_attachment_text(req.attachments)
        extract_message = strip_control_lines(req.message)
        if not extract_message.strip() and not attachment_text.strip():
            empty_resp = TaskAgentResponse(
                status="executed",
                mode="extract",
                intent="mutate_tasks",
                plan=TaskActionPlan(
                    intent_summary="No-op: instruction-only message after guardrail filtering",
                    intent_mode="mutate_tasks",
                    operations=[PlannedOperation(type="noop", payload={}, reason="Instruction-only input", confidence=1.0)],
                    confidence=1.0,
                ),
                execution=TaskExecution(),
                explanation="No actionable extract-mode content found.",
                artifacts={"request_ids": [request_id]},
                notes=["extract_noop_instruction_only"],
                session_id=session_id,
            )
            return self._finalize_contract_response(empty_resp, mode="extract")
        mode = ai.detect_intent_mode(message=extract_message, metadata=req.metadata)
        focus = ai.infer_query_focus(message=req.message)
        allow_task_creation = ai.should_allow_task_creation(message=extract_message, attachment_text=attachment_text, metadata=req.metadata)
        completion_updates = ai.extract_completion_updates(message=extract_message)
        purchase_items = ai.extract_purchase_items(message=extract_message, attachment_text=attachment_text)
        lowered_extract = extract_message.lower()
        explicit_task_list_prompt = self._is_explicit_task_list_prompt(extract_message)
        explicit_create_request = any(
            token in lowered_extract
            for token in ("create ", "add task", "new task", "new list", "new project", "add the items", "add items")
        )
        if self._looks_like_insight_query(extract_message) and not explicit_create_request and not explicit_task_list_prompt:
            mode = "insights_only"
            if not focus.get("topic"):
                focus["topic"] = "general_query"
        existing_task_mutation_phrase = bool(
            re.search(r"\b(mark|complete|move|rename|update)\b", lowered_extract)
            and (
                re.search(r"\btask\s+id\s+\d+\b", lowered_extract)
                or re.search(r"\btask\s+\d+\b", lowered_extract)
                or re.search(r"\btask\b", lowered_extract)
                or re.search(r"\"[^\"]+\"", extract_message)
                or re.search(r"'[^']+'", extract_message)
            )
        )
        if purchase_items and not explicit_create_request:
            allow_task_creation = False
        if completion_updates or existing_task_mutation_phrase:
            allow_task_creation = False
        if explicit_task_list_prompt:
            allow_task_creation = True
        bulk_actions = ai.extract_bulk_actions(message=extract_message, attachment_text=attachment_text)
        team_actions = ai.extract_team_actions(message=extract_message, attachment_text=attachment_text)
        management_actions = ai.extract_management_actions(message=extract_message, attachment_text=attachment_text)
        list_directive = ai.extract_list_directive(message=extract_message, attachment_text=attachment_text)
        destructive_admin_intent = self._contains_destructive_admin_actions(bulk_actions=bulk_actions, management_actions=management_actions)

        if destructive_admin_intent:
            blocked = TaskAgentResponse(
                status="needs_input",
                mode="extract",
                intent="mutate_tasks",
                execution=TaskExecution(),
                explanation="Destructive admin operation requires explicit OPS mode payload.",
                artifacts={"request_ids": [request_id]},
                followups=[
                    "Use OPS mode JSON payload (`mode\":\"ops\"`) for delete/archive/clear operations.",
                    "For bulk list deletes, include a two-phase confirmation phrase in `confirmation` (e.g. `CONFIRM DELETE 3 LISTS`).",
                ],
                notes=["destructive_admin_requires_ops_mode"],
                session_id=session_id,
            )
            return self._finalize_contract_response(blocked, mode="extract")

        lists = self._safe_list_lists(tools)
        all_tasks_by_list = {int(item.get("id")): self._safe_list_tasks(tools, int(item.get("id"))) for item in lists if item.get("id") is not None}

        project_ideas: list[ProjectIdea] = []
        insights = self._build_insights(
            lists,
            all_tasks_by_list,
            tools=tools,
            query_text=req.message,
            focus_topic=focus.get("topic"),
            focus_person=focus.get("person"),
            focus_terms=focus.get("terms") if isinstance(focus.get("terms"), list) else [],
        )

        if mode == "insights_only" and not completion_updates and not purchase_items and not bulk_actions and not team_actions and not management_actions:
            plan = TaskActionPlan(
                intent_summary="Provide read-only task and project insights",
                intent_mode=mode,
                operations=[PlannedOperation(type="noop", payload={}, reason="Insight-only mode", confidence=1.0)],
                confidence=1.0,
                assumptions=["No mutations performed in insights_only mode"],
            )
            resp = TaskAgentResponse(
                status="executed",
                mode="extract",
                intent="insights_only",
                plan=plan,
                execution=TaskExecution(),
                insights=insights,
                project_ideas=[],
                explanation="Generated read-only insights.",
                artifacts={"request_ids": [request_id]},
                session_id=session_id,
            )
            return self._finalize_contract_response(resp, mode="extract")

        candidates = ai.extract_task_candidates(message=extract_message, attachment_text=attachment_text)
        if bool(list_directive.get("create_new_list")) and allow_task_creation:
            explicit_items = ai.extract_itemized_purchase_tasks(message=extract_message)
            if len(explicit_items) >= 2:
                candidates = [ExtractedTask(title=title, confidence=0.9) for title in explicit_items]
        task_titles = [item.title for item in candidates]
        project_ideas = ai.cluster_project_candidates(task_titles)

        operations: list[PlannedOperation] = []
        artifacts: dict[str, list[int | str]] = {
            "request_ids": [request_id],
            "created_list_ids": [],
            "deleted_list_ids": [],
            "archived_list_ids": [],
            "reparented_list_ids": [],
            "created_team_ids": [],
            "shared_list_ids": [],
            "created_task_ids": [],
            "updated_task_ids": [],
            "labeled_task_ids": [],
            "completed_task_ids": [],
            "deleted_task_ids": [],
            "moved_task_ids": [],
            "related_task_ids": [],
            "attachment_task_ids": [],
            "assignee_task_ids": [],
            "priority_task_ids": [],
            "repeat_task_ids": [],
            "progress_task_ids": [],
            "color_task_ids": [],
        }
        missing_info: list[str] = []
        runtime_notes: list[str] = []
        allow_advanced_task_features = str(req.metadata.get("allow_advanced_features") or "").strip().lower() in {"1", "true", "yes"}

        target_project_id: int | None = None
        if bool(list_directive.get("create_new_list")) and str(list_directive.get("list_title") or "").strip():
            operations.append(
                PlannedOperation(
                    type="ensure_list",
                    payload={"title": str(list_directive["list_title"]).strip(), "description": "Explicitly requested list"},
                    reason="User explicitly requested creating a new list/project",
                    confidence=1.0,
                )
            )
        if project_ideas:
            top = project_ideas[0]
            existing_project_id = self._find_existing_list_id(top.title, lists)
            if existing_project_id is not None:
                target_project_id = existing_project_id

        execution = TaskExecution()
        raw_trace: list[dict[str, Any]] = []
        matched_completion_task_ids: set[int] = set()
        insights_query_override: str | None = None

        if management_actions:
            for action in management_actions:
                kind = action.get("action", "")
                if kind in {"delete_projects", "archive_projects"}:
                    # Destructive project/list operations are restricted to OPS mode.
                    continue
                if kind == "move_tasks":
                    # Cross-list bulk movement is treated as admin and requires OPS mode.
                    continue
                if kind in {"reparent_project", "highest_priority_query", "update_task_details", "label_task", "replace_task"}:
                    pass
                else:
                    continue
                if kind == "reparent_project":
                    child_targets = self._resolve_target_list_ids(action.get("target", ""), lists)
                    parent_targets = self._resolve_target_list_ids(action.get("parent", ""), lists)
                    if child_targets and parent_targets:
                        child_id = int(child_targets[0])
                        parent_id = int(parent_targets[0])
                        if child_id != parent_id:
                            op = PlannedOperation(
                                type="reparent_list",
                                payload={
                                    "list_id": child_id,
                                    "parent_list_id": parent_id,
                                    "target": action.get("target", ""),
                                    "parent": action.get("parent", ""),
                                },
                                reason="Explicit request to move project/list under a parent",
                                confidence=0.95,
                            )
                            result = self._execute_operation(op, tools, lists)
                            raw_trace.append({"operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})
                            if result.ok:
                                execution.executed_operations.append(result)
                                artifacts["reparented_list_ids"].append(child_id)
                                lists = self._safe_list_lists(tools)
                                all_tasks_by_list = {
                                    int(item.get("id")): self._safe_list_tasks(tools, int(item.get("id")))
                                    for item in lists
                                    if item.get("id") is not None
                                }
                            else:
                                execution.failed_operations.append(result)
                elif kind == "highest_priority_query":
                    target_ids = self._resolve_target_list_ids(action.get("target", ""), lists)
                    if target_ids:
                        picked = self._highest_priority_open_task(target_ids, all_tasks_by_list, lists)
                        if picked is None:
                            insights_query_override = f"No remaining open tasks found on '{action.get('target', '')}'."
                        else:
                            list_name, task = picked
                            prio = int(task.get("priority") or 0)
                            insights_query_override = f"Highest-priority remaining item on {list_name} is '{task.get('title', '')}' (priority {prio})."
                elif kind == "update_task_details":
                    target_ids = self._resolve_target_list_ids(action.get("list", ""), lists) if action.get("list") else []
                    match = self._match_task_by_text(
                        self._clean_action_target(action.get("target", "")),
                        all_tasks_by_list=all_tasks_by_list,
                        restrict_list_ids=target_ids or None,
                    )
                    if match is not None:
                        _, task = match
                        task_id = _int_or_none(task.get("id"))
                        if task_id is not None:
                            details = str(action.get("details") or "").strip()
                            if details:
                                existing_desc = str(task.get("description") or "").strip()
                                new_desc = details if not existing_desc else f"{existing_desc}\n\n{details}"
                                op = PlannedOperation(
                                    type="update_task",
                                    payload={"task_id": task_id, "patch": {"description": new_desc}},
                                    reason="Explicit request to enrich task details",
                                    confidence=0.9,
                                )
                                result = self._execute_operation(op, tools, lists)
                                raw_trace.append({"operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})
                                if result.ok:
                                    execution.executed_operations.append(result)
                                    artifacts["updated_task_ids"].append(task_id)
                                    task["description"] = new_desc
                                else:
                                    execution.failed_operations.append(result)
                elif kind == "label_task":
                    match = self._match_task_by_text(self._clean_action_target(action.get("target", "")), all_tasks_by_list=all_tasks_by_list)
                    if match is not None:
                        _, task = match
                        task_id = _int_or_none(task.get("id"))
                        label_name = str(action.get("label") or "").strip()
                        if task_id is not None and label_name:
                            op_label = PlannedOperation(
                                type="ensure_label",
                                payload={"title": label_name},
                                reason="Ensure label exists before attaching to task",
                                confidence=0.92,
                            )
                            label_result = self._execute_operation(op_label, tools, lists)
                            raw_trace.append({"operation": op_label.model_dump(mode="json"), "result": label_result.model_dump(mode="json")})
                            if label_result.ok and label_result.result and label_result.result.get("id") is not None:
                                execution.executed_operations.append(label_result)
                                label_id = int(label_result.result["id"])
                                op_attach = PlannedOperation(
                                    type="add_label_to_task",
                                    payload={"task_id": task_id, "label_id": label_id},
                                    reason="Attach requested label to matched task",
                                    confidence=0.9,
                                )
                                attach_result = self._execute_operation(op_attach, tools, lists)
                                raw_trace.append({"operation": op_attach.model_dump(mode="json"), "result": attach_result.model_dump(mode="json")})
                                if attach_result.ok:
                                    execution.executed_operations.append(attach_result)
                                    artifacts["labeled_task_ids"].append(task_id)
                                else:
                                    execution.failed_operations.append(attach_result)
                            else:
                                execution.failed_operations.append(label_result)
                elif kind == "replace_task":
                    target_ids = self._resolve_target_list_ids(action.get("list", ""), lists) if action.get("list") else []
                    match = self._match_task_by_text(
                        self._clean_action_target(action.get("target", "")),
                        all_tasks_by_list=all_tasks_by_list,
                        restrict_list_ids=target_ids or None,
                    )
                    if match is not None:
                        list_id, task = match
                        task_id = _int_or_none(task.get("id"))
                        replacement = str(action.get("replacement") or "").strip()
                        if task_id is not None and replacement:
                            op_del = PlannedOperation(
                                type="delete_task",
                                payload={"task_id": task_id, "list_id": list_id},
                                reason="Replace requested task with new item",
                                confidence=0.9,
                            )
                            del_result = self._execute_operation(op_del, tools, lists)
                            raw_trace.append({"operation": op_del.model_dump(mode="json"), "result": del_result.model_dump(mode="json")})
                            if del_result.ok:
                                execution.executed_operations.append(del_result)
                                artifacts["deleted_task_ids"].append(task_id)
                                all_tasks_by_list[list_id] = [item for item in all_tasks_by_list.get(list_id, []) if _int_or_none(item.get("id")) != task_id]
                                op_add = PlannedOperation(
                                    type="create_task",
                                    payload={"list_id": list_id, "title": replacement, "description": ""},
                                    reason="Replacement task requested",
                                    confidence=0.9,
                                )
                                add_result = self._execute_operation(op_add, tools, lists)
                                raw_trace.append({"operation": op_add.model_dump(mode="json"), "result": add_result.model_dump(mode="json")})
                                if add_result.ok:
                                    execution.executed_operations.append(add_result)
                                    created_id = _int_or_none((add_result.result or {}).get("id"))
                                    if created_id is not None:
                                        artifacts["created_task_ids"].append(created_id)
                                    all_tasks_by_list.setdefault(list_id, []).append(add_result.result or {"title": replacement})
                                else:
                                    execution.failed_operations.append(add_result)
                            else:
                                execution.failed_operations.append(del_result)
        if bulk_actions:
            for action in bulk_actions:
                # Destructive bulk actions are restricted to OPS mode.
                if action.get("action") == "clear_tasks":
                    continue

        if team_actions:
            for action in team_actions:
                if action.get("action") != "share_list":
                    continue
                target_list_ids = self._resolve_target_list_ids(action.get("target", ""), lists)
                if not target_list_ids:
                    target_list_ids = self._resolve_target_list_ids_from_tasks(
                        action.get("target", ""),
                        lists=lists,
                        all_tasks_by_list=all_tasks_by_list,
                    )
                if not target_list_ids:
                    continue
                team_result = self._ensure_team(action.get("team", ""), tools)
                if team_result is None:
                    execution.failed_operations.append(
                        ExecutionOperationResult(
                            type="ensure_team",
                            payload={"team": action.get("team", "")},
                            ok=False,
                            error="Unable to resolve or create team",
                        )
                    )
                    continue
                team_id, team_created = team_result
                if team_created:
                    artifacts["created_team_ids"].append(team_id)
                for list_id in target_list_ids:
                    op = PlannedOperation(
                        type="share_list_with_team",
                        payload={"list_id": list_id, "team_id": team_id, "team_name": action.get("team", "")},
                        reason="Explicit user request to assign/share list with team",
                        confidence=0.95,
                    )
                    result = self._execute_operation(op, tools, lists)
                    raw_trace.append({"operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})
                    if result.ok:
                        execution.executed_operations.append(result)
                        artifacts["shared_list_ids"].append(list_id)
                    else:
                        execution.failed_operations.append(result)

        if completion_updates:
            for update in completion_updates:
                matched = self._match_existing_task_for_completion(update_target=update["target"], all_tasks_by_list=all_tasks_by_list)
                if matched is None:
                    continue
                list_id, task = matched
                task_id = _int_or_none(task.get("id"))
                if task_id is None:
                    continue
                matched_completion_task_ids.add(task_id)
                patch: dict[str, Any] = {"done": True}
                op = PlannedOperation(
                    type="update_task",
                    payload={
                        "task_id": task_id,
                        "patch": patch,
                        "matched_target": update["target"],
                        "source_text": update["raw"],
                    },
                    reason="Detected completion-style update and mapped to existing task",
                    confidence=0.9,
                )
                result = self._execute_operation(op, tools, lists)
                raw_trace.append({"operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})
                if result.ok:
                    execution.executed_operations.append(result)
                    artifacts["completed_task_ids"].append(task_id)
                    # Keep in-memory snapshot aligned for subsequent matching.
                    task["done"] = True
                else:
                    execution.failed_operations.append(result)

        for op in operations:
            result = self._execute_operation(op, tools, lists)
            raw_trace.append({"operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})
            if result.ok:
                execution.executed_operations.append(result)
                created_id = result.result.get("id") if result.result else None
                created_flag = bool(result.result.get("_created")) if result.result else False
                if op.type == "ensure_list" and created_id is not None:
                    artifacts["created_list_ids"].append(created_id)
                    target_project_id = int(created_id)
                    lists = self._safe_list_lists(tools)
                    all_tasks_by_list = {int(item.get("id")): self._safe_list_tasks(tools, int(item.get("id"))) for item in lists if item.get("id") is not None}
                    if not created_flag:
                        artifacts["created_list_ids"] = [item for item in artifacts["created_list_ids"] if item != created_id]
            else:
                execution.failed_operations.append(result)

        if allow_task_creation:
            for item in candidates:
                if self._is_non_task_header_candidate(item.title):
                    runtime_notes.append(f"skipped_non_task_header:{item.title}")
                    continue
                normalized_dates, date_issues = self._normalize_candidate_dates(item=item, metadata=req.metadata)
                if date_issues:
                    missing_info.extend(date_issues)
                    continue
                if item.ambiguities and not explicit_task_list_prompt:
                    blocking_ambiguities: list[str] = []
                    for msg in item.ambiguities:
                        lowered_msg = str(msg).lower()
                        if (
                            normalized_dates.get("due_date")
                            and ("timezone" in lowered_msg or "tomorrow" in lowered_msg or "relative date" in lowered_msg)
                        ):
                            continue
                        blocking_ambiguities.append(msg)
                    if blocking_ambiguities:
                        missing_info.extend([f"Task '{item.title}': {msg}" for msg in blocking_ambiguities])
                        continue
                list_id = target_project_id
                if item.target_project:
                    match_ids = self._resolve_target_list_ids(item.target_project, lists)
                    if match_ids:
                        list_id = int(match_ids[0])
                    else:
                        ensured_target = tools.ensure_list(item.target_project.strip())
                        list_id = _int_or_none(ensured_target.get("id"))
                        lists = self._safe_list_lists(tools)
                if list_id is not None and item.parent_project:
                    parent_ids = self._resolve_target_list_ids(item.parent_project, lists)
                    parent_id = int(parent_ids[0]) if parent_ids else None
                    if parent_id is None:
                        ensured_parent = tools.ensure_list(item.parent_project.strip())
                        parent_id = _int_or_none(ensured_parent.get("id"))
                        lists = self._safe_list_lists(tools)
                    if parent_id is not None and parent_id != list_id:
                        rep = self._execute_operation(
                            PlannedOperation(
                                type="reparent_list",
                                payload={"list_id": int(list_id), "parent_list_id": int(parent_id)},
                                reason="Auto parent project association from extracted task context",
                                confidence=max(0.65, item.confidence),
                            ),
                            tools,
                            lists,
                        )
                        raw_trace.append({"operation": "reparent_list", "result": rep.model_dump(mode="json")})
                        if rep.ok:
                            execution.executed_operations.append(rep)
                            artifacts["reparented_list_ids"].append(int(list_id))
                        else:
                            execution.failed_operations.append(rep)
                if list_id is not None and bool(list_directive.get("create_new_list")):
                    list_name = str(list_directive.get("list_title") or "")
                else:
                    list_name = (
                        project_ideas[0].title if (list_id is not None and project_ideas) else ai.infer_list_name(item.title)
                    )
                if list_id is None:
                    known_ids_before = {int(entry.get("id")) for entry in lists if entry.get("id") is not None}
                    ensured = tools.ensure_list(list_name)
                    list_id = int(ensured.get("id")) if ensured.get("id") is not None else None
                    if list_id is not None and int(list_id) not in artifacts["created_list_ids"] and int(list_id) not in known_ids_before:
                        existing = [int(v) for v in artifacts["created_list_ids"] if isinstance(v, int)]
                        if int(list_id) not in existing:
                            artifacts["created_list_ids"].append(int(list_id))
                    lists = self._safe_list_lists(tools)
                if list_id is None:
                    execution.failed_operations.append(
                        ExecutionOperationResult(type="create_task", payload={"title": item.title, "list_name": list_name}, ok=False, error="Unable to resolve list id")
                    )
                    continue
                existing_titles = [str(task.get("title") or "") for task in all_tasks_by_list.get(int(list_id), [])]
                if self._has_similar_title(item.title, existing_titles):
                    runtime_notes.append(f"skipped_duplicate:{item.title}")
                    continue
                if self._is_similar_to_completed_match(item.title, all_tasks_by_list, matched_completion_task_ids):
                    runtime_notes.append(f"skipped_duplicate_completed:{item.title}")
                    continue
                op = PlannedOperation(
                    type="create_task",
                    payload={
                        "list_id": int(list_id),
                        "title": item.title,
                        "description": str(item.description or ""),
                        "due_date": normalized_dates.get("due_date"),
                        "start_date": normalized_dates.get("start_date"),
                        "end_date": normalized_dates.get("end_date"),
                        "priority": item.priority,
                    },
                    reason="Extracted actionable task",
                    confidence=item.confidence,
                )
                result = self._execute_operation(op, tools, lists)
                raw_trace.append({"operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})
                if result.ok:
                    execution.executed_operations.append(result)
                    created_id = result.result.get("id") if result.result else None
                    if created_id is not None:
                        artifacts["created_task_ids"].append(int(created_id))
                    created_task_id = _int_or_none(created_id)
                    created_task = result.result or {"title": item.title}
                    all_tasks_by_list.setdefault(int(list_id), []).append(created_task)
                    if created_task_id is not None and allow_advanced_task_features:
                        if not item.attachments and req.attachments and len(candidates) == 1:
                            for attachment in req.attachments:
                                payload: dict[str, str] = {}
                                if getattr(attachment, "url", None):
                                    payload["url"] = str(getattr(attachment, "url"))
                                if getattr(attachment, "bytes_base64", None):
                                    payload["bytes_base64"] = str(getattr(attachment, "bytes_base64"))
                                if getattr(attachment, "name", None):
                                    payload["filename"] = str(getattr(attachment, "name"))
                                if payload:
                                    item.attachments.append(payload)
                        advanced_results = self._apply_advanced_task_features(
                            task_id=created_task_id,
                            task=item,
                            list_id=int(list_id),
                            tools=tools,
                            lists=lists,
                            capabilities=capabilities,
                            all_tasks_by_list=all_tasks_by_list,
                        )
                        raw_trace.extend(advanced_results["trace"])
                        execution.executed_operations.extend(advanced_results["executed"])
                        execution.failed_operations.extend(advanced_results["failed"])
                        for key, values in advanced_results["artifacts"].items():
                            if key in artifacts:
                                artifacts[key].extend(values)
                else:
                    execution.failed_operations.append(result)

        if purchase_items:
            reconciliation = self._reconcile_purchase_items(purchase_items, all_tasks_by_list, tools)
            raw_trace.extend(reconciliation["trace"])
            execution.executed_operations.extend(reconciliation["executed"])
            execution.failed_operations.extend(reconciliation["failed"])
            artifacts["completed_task_ids"].extend(reconciliation["completed_task_ids"])

        followups: list[str] = []
        status = "executed"
        if missing_info:
            status = "needs_input"
            followups.extend(sorted(dict.fromkeys(missing_info))[:8])
        elif not candidates and not purchase_items and not execution.executed_operations and not execution.failed_operations and insights_query_override is None and not management_actions:
            status = "needs_input"
            followups.append("Provide more specific task details or attach notes with actionable items.")
        elif execution.failed_operations and not execution.executed_operations:
            status = "failed"

        plan = TaskActionPlan(
            intent_summary="Extract tasks, route to lists/projects, reconcile purchase-like items, and optionally provide insights",
            intent_mode=mode,
            operations=operations,
            confidence=max([op.confidence for op in operations], default=0.8 if candidates else 0.5),
            missing_info=sorted(dict.fromkeys(missing_info)),
            assumptions=[
                "No default list is used; list names are inferred and created when needed.",
                "Purchase-like extracted content is reconciled against all managed lists.",
                "Task creation is suppressed unless explicitly requested by the user.",
            ],
        )

        resp = TaskAgentResponse(
            status=status,
            mode="extract",
            intent=mode,
            plan=plan,
            execution=execution,
            insights=self._apply_query_override(insights, insights_query_override) if mode in {"insights_only", "hybrid"} else None,
            project_ideas=project_ideas,
            explanation="Task processing completed." if status == "executed" else "Task processing needs more input." if status == "needs_input" else "Task processing failed.",
            followups=followups,
            artifacts=artifacts,
            raw_tool_trace=raw_trace,
            notes=sorted(dict.fromkeys(runtime_notes)),
            session_id=session_id,
        )
        return self._finalize_contract_response(resp, mode="extract")

    def _is_explicit_task_list_prompt(self, text: str) -> bool:
        lowered = (text or "").lower()
        if "here are tasks" in lowered or "task list" in lowered:
            return True
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        bullet_count = sum(1 for line in lines if line.startswith(("- ", "* ", "• ")))
        return bullet_count >= 2

    def _is_non_task_header_candidate(self, title: str) -> bool:
        lowered = (title or "").strip().lower()
        if not lowered:
            return True
        if lowered.startswith("extract mode test"):
            return True
        if lowered.startswith("here are tasks"):
            return True
        if "do not turn the next line into a task" in lowered:
            return True
        return False

    def _looks_like_insight_query(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        if "?" in lowered:
            return True
        patterns = (
            r"\bget_all_projects\b",
            r"\bget_all_tasks\b",
            r"^what\s+",
            r"^show\s+",
            r"^list\s+",
            r"^have\s+i\s+",
            r"\bwork\s+next\b",
            r"\bstatus\b",
            r"\boverview\b",
            r"\bsummary\b",
        )
        return any(re.search(p, lowered) for p in patterns)

    def _run_ops_mode(
        self,
        *,
        req: TaskInvokeRequest,
        envelope: OpsEnvelope,
        tools: TaskTools,
        request_id: str,
        session_id: str,
    ) -> TaskAgentResponse:
        execution = TaskExecution()
        trace: list[dict[str, Any]] = []
        artifacts: dict[str, list[int | str]] = {
            "request_ids": [request_id],
            "created_task_ids": [],
            "updated_task_ids": [],
            "moved_task_ids": [],
            "created_list_ids": [],
            "deleted_list_ids": [],
            "archived_list_ids": [],
        }
        notes: list[str] = []
        bulk_delete_ops = [op for op in envelope.operations if isinstance(op, DeleteListOp)]
        unique_bulk_delete_ids = sorted({int(op.list_id) for op in bulk_delete_ops})
        if len(unique_bulk_delete_ids) >= 2:
            existing_list_ids = sorted({int(item.get("id")) for item in self._safe_list_lists(tools) if item.get("id") is not None})
            keep_ids = [list_id for list_id in existing_list_ids if list_id not in unique_bulk_delete_ids]
            required_confirmation = f"CONFIRM DELETE {len(unique_bulk_delete_ids)} LISTS"
            provided_confirmation = str(envelope.confirmation or "").strip().upper()
            if provided_confirmation != required_confirmation:
                plan_row = f"I will delete lists: {unique_bulk_delete_ids}; keep: {keep_ids}."
                response = TaskAgentResponse(
                    status="needs_input",
                    mode="ops",
                    intent="ops",
                    execution=TaskExecution(),
                    explanation=plan_row,
                    artifacts=artifacts,
                    raw_tool_trace=[],
                    notes=["bulk_delete_requires_confirmation"],
                    followups=[
                        f'Phase 2 confirmation required: send OPS payload with `confirmation` set to "{required_confirmation}".',
                    ],
                    session_id=session_id,
                )
                return self._finalize_contract_response(response, mode="ops")

        for index, op in enumerate(envelope.operations):
            try:
                if isinstance(op, EnsureListOp):
                    known_ids = {int(item.get("id")) for item in self._safe_list_lists(tools) if item.get("id") is not None}
                    out = tools.ensure_list(op.title, description=op.description)
                    result = ExecutionOperationResult(type="ensure_list", payload=op.model_dump(mode="json"), ok=True, result=out)
                    created_id = _int_or_none((out or {}).get("id"))
                    if created_id is not None and created_id not in known_ids:
                        artifacts["created_list_ids"].append(created_id)
                elif isinstance(op, RenameListOp):
                    out = tools.rename_list(int(op.list_id), op.title)
                    result = ExecutionOperationResult(type="rename_list", payload=op.model_dump(mode="json"), ok=True, result=out)
                elif isinstance(op, MoveTaskOp):
                    target_list_id, err = self._resolve_ops_list_target(op.list_id, op.list_id_ref, tools)
                    if err:
                        raise ValueError(err)
                    out = tools.move_task(int(op.task_id), int(target_list_id))
                    result = ExecutionOperationResult(type="move_task", payload=op.model_dump(mode="json"), ok=True, result=out)
                    artifacts["moved_task_ids"].append(int(op.task_id))
                elif isinstance(op, CreateTaskOp):
                    target_list_id, err = self._resolve_ops_list_target(op.list_id, op.list_id_ref, tools)
                    if err:
                        raise ValueError(err)
                    out = tools.create_task(
                        int(target_list_id),
                        title=op.title,
                        description=op.description,
                        due_date=op.due_date,
                    )
                    result = ExecutionOperationResult(type="create_task", payload=op.model_dump(mode="json"), ok=True, result=out)
                    created_id = _int_or_none((out or {}).get("id"))
                    if created_id is not None:
                        artifacts["created_task_ids"].append(created_id)
                elif isinstance(op, UpdateTaskOp):
                    out = tools.update_task(int(op.task_id), patch=dict(op.patch))
                    result = ExecutionOperationResult(type="update_task", payload=op.model_dump(mode="json"), ok=True, result=out)
                    artifacts["updated_task_ids"].append(int(op.task_id))
                elif isinstance(op, CompleteTaskOp):
                    out = tools.update_task(int(op.task_id), patch={"done": True})
                    result = ExecutionOperationResult(type="complete_task", payload=op.model_dump(mode="json"), ok=True, result=out)
                    artifacts["updated_task_ids"].append(int(op.task_id))
                elif isinstance(op, DeleteTaskOp):
                    out = tools.delete_task(int(op.task_id))
                    result = ExecutionOperationResult(type="delete_task", payload=op.model_dump(mode="json"), ok=True, result=out)
                elif isinstance(op, DeleteListOp):
                    out = tools.delete_list(int(op.list_id))
                    result = ExecutionOperationResult(type="delete_list", payload=op.model_dump(mode="json"), ok=True, result=out)
                    artifacts["deleted_list_ids"].append(int(op.list_id))
                elif isinstance(op, ArchiveListOp):
                    out = tools.archive_list(int(op.list_id), archived=bool(op.archived))
                    result = ExecutionOperationResult(type="archive_list", payload=op.model_dump(mode="json"), ok=True, result=out)
                    if bool(op.archived):
                        artifacts["archived_list_ids"].append(int(op.list_id))
                elif isinstance(op, GetTassksOp):
                    out = tools.get_task(int(op.task_id))
                    if not out:
                        raise KeyError(f"task_not_found:{int(op.task_id)}")
                    minimal = {
                        "id": _int_or_none(out.get("id")),
                        "title": str(out.get("title") or ""),
                        "description": str(out.get("description") or ""),
                        "due_date": out.get("due_date"),
                        "project_id": _int_or_none(out.get("project_id")),
                    }
                    result = ExecutionOperationResult(type="get_task", payload=op.model_dump(mode="json"), ok=True, result=minimal)
                elif isinstance(op, GetAllProjectsOp):
                    rows = self._deterministic_project_rows(self._safe_list_lists(tools), tools=tools)
                    result = ExecutionOperationResult(type="get_all_projects", payload=op.model_dump(mode="json"), ok=True, result={"items": rows})
                elif isinstance(op, GetAllTasksOp):
                    rows = self._deterministic_project_rows(self._safe_list_lists(tools), tools=tools)
                    result = ExecutionOperationResult(type="get_all_tasks", payload=op.model_dump(mode="json"), ok=True, result={"items": rows})
                else:
                    raise ValueError(f"unsupported_op_type:{type(op).__name__}")
            except Exception as exc:
                result = ExecutionOperationResult(
                    type=getattr(op, "type", "noop"),
                    payload=op.model_dump(mode="json"),
                    ok=False,
                    error=str(exc),
                )
                execution.failed_operations.append(result)
                trace.append({"index": index, "operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})
                if envelope.stop_on_error:
                    notes.append("stop_on_error_triggered")
                    break
                continue

            execution.executed_operations.append(result)
            trace.append({"index": index, "operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})

        status = "executed"
        if execution.failed_operations and not execution.executed_operations:
            status = "failed"
        elif execution.failed_operations:
            notes.append("partial_failure")

        response = TaskAgentResponse(
            status=status,
            mode="ops",
            intent="ops",
            execution=execution,
            explanation="OPS execution completed.",
            artifacts=artifacts,
            raw_tool_trace=trace,
            notes=notes,
            session_id=session_id,
        )
        return self._finalize_contract_response(response, mode="ops")

    def _resolve_ops_list_target(self, list_id: int | None, list_id_ref: str | None, tools: TaskTools) -> tuple[int | None, str | None]:
        if list_id is not None:
            return int(list_id), None
        title = str(list_id_ref or "").strip()
        if not title:
            return None, "list_target_required"
        rows = self._safe_list_lists(tools)
        matches = [
            int(item.get("id"))
            for item in rows
            if item.get("id") is not None and str(item.get("title") or "").strip().lower() == title.lower()
        ]
        if not matches:
            return None, "list_id_ref_not_found"
        unique = sorted(set(matches))
        if len(unique) != 1:
            return None, "list_id_ref_ambiguous"
        return int(unique[0]), None

    def _finalize_contract_response(self, response: TaskAgentResponse, *, mode: str) -> TaskAgentResponse:
        artifacts = response.artifacts or {}
        executed = [item.model_dump(mode="json") for item in response.execution.executed_operations]
        failed = [item.model_dump(mode="json") for item in response.execution.failed_operations]
        return response.model_copy(
            update={
                "mode": mode,
                "executed_operations": executed,
                "failed_operations": failed,
                "created_task_ids": [int(v) for v in artifacts.get("created_task_ids", []) if _int_or_none(v) is not None],
                "updated_task_ids": [int(v) for v in artifacts.get("updated_task_ids", []) if _int_or_none(v) is not None],
                "moved_task_ids": [int(v) for v in artifacts.get("moved_task_ids", []) if _int_or_none(v) is not None],
                "created_list_ids": [int(v) for v in artifacts.get("created_list_ids", []) if _int_or_none(v) is not None],
                "notes": list(response.notes or []),
            }
        )

    def _execute_operation(self, op: PlannedOperation, tools: TaskTools, lists: list[dict[str, Any]]) -> ExecutionOperationResult:
        try:
            if op.type == "ensure_list":
                known_ids_before = {int(entry.get("id")) for entry in tools.list_lists() if entry.get("id") is not None}
                result = tools.ensure_list(op.payload["title"], description=str(op.payload.get("description") or ""))
                resolved_id = int(result.get("id")) if result.get("id") is not None else None
                created = resolved_id is not None and resolved_id not in known_ids_before
                merged = dict(result)
                merged["_created"] = created
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=merged)
            if op.type == "delete_list":
                result = tools.delete_list(int(op.payload["list_id"]))
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "archive_list":
                result = tools.archive_list(int(op.payload["list_id"]), archived=bool(op.payload.get("is_archived", True)))
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "rename_list":
                result = tools.rename_list(int(op.payload["list_id"]), str(op.payload["title"]))
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "reparent_list":
                result = tools.set_list_parent(int(op.payload["list_id"]), int(op.payload["parent_list_id"]))
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "create_task":
                result = tools.create_task(
                    int(op.payload["list_id"]),
                    title=str(op.payload["title"]),
                    description=str(op.payload.get("description") or ""),
                    due_date=str(op.payload.get("due_date") or "") or None,
                    start_date=str(op.payload.get("start_date") or "") or None,
                    end_date=str(op.payload.get("end_date") or "") or None,
                    priority=_int_or_none(op.payload.get("priority")),
                )
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "complete_task":
                result = tools.update_task(int(op.payload["task_id"]), patch={"done": True})
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "reopen_task":
                result = tools.update_task(int(op.payload["task_id"]), patch={"done": False})
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "update_task":
                result = tools.update_task(int(op.payload["task_id"]), patch=dict(op.payload.get("patch") or {}))
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "comment_task":
                patch = {"description": str(op.payload.get("comment") or "")}
                result = tools.update_task(int(op.payload["task_id"]), patch=patch)
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "delete_task":
                result = tools.delete_task(int(op.payload["task_id"]))
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "ensure_team":
                team_name = str(op.payload.get("team") or "").strip()
                resolved = self._ensure_team(team_name, tools)
                if resolved is None:
                    return ExecutionOperationResult(type=op.type, payload=op.payload, ok=False, error="Unable to ensure team")
                team_id, created = resolved
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result={"id": team_id, "created": created, "name": team_name})
            if op.type == "share_list_with_team":
                result = tools.share_list_with_team(int(op.payload["list_id"]), int(op.payload["team_id"]), permission=int(op.payload.get("permission", 0)))
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "ensure_label":
                result = tools.ensure_label(str(op.payload.get("title") or "").strip())
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "add_label_to_task":
                result = tools.add_label_to_task(int(op.payload["task_id"]), int(op.payload["label_id"]))
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "set_task_assignees":
                result = tools.set_task_assignees(int(op.payload["task_id"]), [int(v) for v in op.payload.get("assignee_ids", [])])
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "set_task_progress":
                result = tools.set_task_progress(int(op.payload["task_id"]), float(op.payload.get("progress") or 0.0))
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "set_task_color":
                result = tools.set_task_color(int(op.payload["task_id"]), str(op.payload.get("color") or ""))
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "set_task_repeat":
                result = tools.set_task_repeat(int(op.payload["task_id"]), int(op.payload.get("repeat_after_seconds") or 0))
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "add_task_relation":
                result = tools.add_task_relation(
                    int(op.payload["task_id"]),
                    int(op.payload["other_task_id"]),
                    str(op.payload.get("relation_type") or task_settings.task_agent_relation_default),
                )
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "add_task_attachment":
                result = tools.add_task_attachment(
                    int(op.payload["task_id"]),
                    url=str(op.payload.get("url") or "") or None,
                    filename=str(op.payload.get("filename") or "") or None,
                    bytes_base64=str(op.payload.get("bytes_base64") or "") or None,
                )
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            if op.type == "move_task":
                result = tools.move_task(int(op.payload["task_id"]), int(op.payload["project_id"]))
                return ExecutionOperationResult(type=op.type, payload=op.payload, ok=True, result=result)
            return ExecutionOperationResult(type="noop", payload=op.payload, ok=True, result={})
        except Exception as exc:
            return ExecutionOperationResult(type=op.type, payload=op.payload, ok=False, error=str(exc))

    def _build_insights(
        self,
        lists: list[dict[str, Any]],
        all_tasks_by_list: dict[int, list[dict[str, Any]]],
        tools: TaskTools,
        *,
        query_text: str = "",
        focus_topic: str | None = None,
        focus_person: str | None = None,
        focus_terms: list[str] | None = None,
    ) -> TaskInsights:
        focus_terms = focus_terms or []
        asks_get_all_projects = self._is_get_all_projects_query(query_text)
        asks_get_all_tasks = self._is_get_all_tasks_query(query_text)
        asks_project_listing = self._is_project_listing_query(query_text)
        asks_team_listing = self._is_team_listing_query(query_text)
        team_members_target = self._extract_team_members_target(query_text)
        asks_archived_projects_listing = self._is_archived_projects_listing_query(query_text)
        label_target = self._extract_label_task_query_label(query_text)
        asks_structured_listing = bool(
            asks_get_all_projects
            or asks_get_all_tasks
            or asks_project_listing
            or asks_team_listing
            or team_members_target
            or asks_archived_projects_listing
            or label_target
        )
        asks_chores_left = ("chore" in query_text.lower() or "chores" in query_text.lower()) and any(
            token in query_text.lower() for token in ("girls", "girl")
        )
        work_next_person = self._extract_work_next_person(query_text)
        work_next_user_ids: set[int] = set()
        work_next_team_project_ids: set[int] = set()
        work_next_team_names: set[str] = set()
        if work_next_person:
            work_next_user_ids = self._resolve_user_ids_by_name(
                requested_name=work_next_person,
                tools=tools,
                lists=lists,
                all_tasks_by_list=all_tasks_by_list,
            )
            if work_next_user_ids:
                team_ids: set[int] = set()
                for team in self._safe_list_teams(tools):
                    team_id = _int_or_none(team.get("id"))
                    if team_id is None:
                        continue
                    members = self._safe_list_team_members(tools, team_id)
                    embedded_members = team.get("members") if isinstance(team.get("members"), list) else []
                    merged_members = [item for item in [*members, *embedded_members] if isinstance(item, dict)]
                    member_ids = {_int_or_none(item.get("id")) for item in merged_members}
                    creator_id = _int_or_none((team.get("created_by") or {}).get("id")) if isinstance(team.get("created_by"), dict) else None
                    if any(uid in member_ids for uid in work_next_user_ids) or (creator_id is not None and creator_id in work_next_user_ids):
                        team_ids.add(team_id)
                        team_name = str(team.get("name") or "").strip()
                        if team_name:
                            work_next_team_names.add(team_name)
                for list_item in lists:
                    list_id = _int_or_none(list_item.get("id"))
                    if list_id is None:
                        continue
                    teams = self._safe_list_list_teams(tools, list_id)
                    linked = {_int_or_none(item.get("id")) for item in teams}
                    if any(tid in linked for tid in team_ids):
                        work_next_team_project_ids.add(list_id)
        now = datetime.now(UTC)
        due_soon: list[InsightTaskItem] = []
        overdue: list[InsightTaskItem] = []
        stale: list[InsightTaskItem] = []
        relevant: list[InsightTaskItem] = []
        work_next_items: list[InsightTaskItem] = []
        semantic_fallback_items: list[InsightTaskItem] = []
        total_open = 0
        total_done = 0

        for list_item in lists:
            list_id = int(list_item.get("id")) if list_item.get("id") is not None else None
            list_name = str(list_item.get("title") or "")
            semantically_matched_list = self._is_semantic_list_match_for_person(
                list_name=list_name,
                person_name=work_next_person,
                team_names=work_next_team_names,
            )
            tasks = all_tasks_by_list.get(list_id or -1, [])
            for task in tasks:
                done = bool(task.get("done"))
                if done:
                    total_done += 1
                else:
                    total_open += 1
                title = str(task.get("title") or "")
                done = bool(task.get("done"))
                due_str = _coerce_date(str(task.get("due_date") or "") or None)
                relevance_score = self._relevance_score(
                    title=title,
                    list_name=list_name,
                    topic=focus_topic,
                    person=focus_person,
                    terms=focus_terms,
                    query_text=query_text,
                )
                assignee_ids = {_int_or_none(item.get("id")) for item in (task.get("assignees") or []) if isinstance(item, dict)}
                created_by_id = _int_or_none((task.get("created_by") or {}).get("id")) if isinstance(task.get("created_by"), dict) else None
                list_owner_id = _int_or_none((list_item.get("owner") or {}).get("id")) if isinstance(list_item.get("owner"), dict) else None
                is_work_next_match = bool(work_next_user_ids) and not done and (
                    any(uid in assignee_ids for uid in work_next_user_ids)
                    or (created_by_id is not None and created_by_id in work_next_user_ids)
                    or (list_owner_id is not None and list_owner_id in work_next_user_ids)
                    or (list_id is not None and list_id in work_next_team_project_ids)
                )
                if relevance_score >= 0.35 or (asks_chores_left and self._is_girls_chores_list(str(list_item.get("title") or ""))) or is_work_next_match:
                    relevant.append(
                        InsightTaskItem(
                            task_id=_int_or_none(task.get("id")),
                            list_id=list_id,
                            list_name=list_name,
                            title=title,
                            due_date=due_str,
                            done=done,
                        )
                    )
                if is_work_next_match:
                    work_next_items.append(
                        InsightTaskItem(
                            task_id=_int_or_none(task.get("id")),
                            list_id=list_id,
                            list_name=list_name,
                            title=title,
                            due_date=due_str,
                            done=done,
                        )
                    )
                if not done and due_str:
                    due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
                    delta = due_dt - now
                    item = InsightTaskItem(
                        task_id=_int_or_none(task.get("id")),
                        list_id=list_id,
                        list_name=list_name,
                        title=title,
                        due_date=due_str,
                        done=False,
                    )
                    if delta.total_seconds() < 0:
                        overdue.append(item)
                    elif delta.total_seconds() <= 3 * 86400:
                        due_soon.append(item)
                if not done and task.get("updated"):
                    stale.append(
                        InsightTaskItem(
                            task_id=_int_or_none(task.get("id")),
                            list_id=list_id,
                            list_name=list_name,
                            title=title,
                            done=False,
                        )
                    )
                if not done:
                    if semantically_matched_list:
                        semantic_fallback_items.append(
                            InsightTaskItem(
                                task_id=_int_or_none(task.get("id")),
                                list_id=list_id,
                                list_name=list_name,
                                title=title,
                                due_date=due_str,
                                done=False,
                            )
                        )

        recommendations: list[str] = []
        if overdue:
            recommendations.append(f"Resolve {len(overdue)} overdue task(s) first.")
        if focus_topic == "general_query" and not asks_structured_listing:
            recommendations.append(f"Relevant tasks found: {len(relevant)}.")
        if due_soon:
            recommendations.append("Review due-soon tasks and confirm owners/next actions.")
        if not recommendations:
            recommendations.append("No urgent issues detected.")

        query_answer = None
        deterministic_rows = self._deterministic_project_rows(lists, tools=tools)
        if focus_topic == "general_query" or asks_structured_listing:
            if asks_get_all_projects:
                query_answer = json.dumps(deterministic_rows, separators=(",", ":"), sort_keys=True)
            elif asks_get_all_tasks:
                query_answer = json.dumps(deterministic_rows, separators=(",", ":"), sort_keys=True)
            elif team_members_target:
                team = self._find_team_by_name(team_members_target, tools=tools)
                if team is None:
                    query_answer = f"No team found matching '{team_members_target}'."
                else:
                    team_id = _int_or_none(team.get("id"))
                    members = self._safe_list_team_members(tools, team_id) if team_id is not None else []
                    embedded_members = team.get("members") if isinstance(team.get("members"), list) else []
                    merged = [item for item in [*members, *embedded_members] if isinstance(item, dict)]
                    unique_members = self._unique_user_rows(merged)
                    team_name = str(team.get("name") or team_members_target).strip() or team_members_target
                    if unique_members:
                        display = ", ".join(unique_members[:20])
                        query_answer = f"Members in {team_name}: {display}."
                    else:
                        query_answer = f"No members found in {team_name}."
            elif asks_team_listing:
                teams = self._safe_list_teams(tools)
                names = sorted(
                    {str(item.get("name") or "").strip() for item in teams if str(item.get("name") or "").strip()},
                    key=str.lower,
                )
                if names:
                    query_answer = f"Teams ({len(names)}): {', '.join(names[:25])}."
                else:
                    query_answer = "No teams found."
            elif asks_archived_projects_listing:
                archived_rows = self._project_rows(lists=lists, all_tasks_by_list=all_tasks_by_list, include_archived=True, archived_only=True)
                if archived_rows:
                    query_answer = f"Archived projects ({len(archived_rows)}): {', '.join(archived_rows[:20])}."
                else:
                    query_answer = "No archived projects found."
            elif label_target:
                labeled = self._tasks_with_label(
                    label_name=label_target,
                    lists=lists,
                    all_tasks_by_list=all_tasks_by_list,
                )
                if labeled:
                    query_answer = f"Tasks labeled {label_target} ({len(labeled)}): {', '.join(labeled[:25])}."
                else:
                    query_answer = f"No tasks found labeled {label_target}."
            elif asks_project_listing:
                include_archived = any(token in query_text.lower() for token in ("archived", "archive"))
                project_rows = self._project_rows(lists=lists, all_tasks_by_list=all_tasks_by_list, include_archived=include_archived)
                if project_rows:
                    query_answer = f"Projects ({len(project_rows)}): " + ", ".join(project_rows[:15]) + "."
                else:
                    query_answer = "No projects found."
            subject = focus_person or "The user"
            ranked_relevant = sorted(
                relevant,
                key=lambda item: self._relevance_score(
                    title=item.title,
                    list_name=item.list_name,
                    topic=focus_topic,
                    person=focus_person,
                    terms=focus_terms,
                    query_text=query_text,
                ),
                reverse=True,
            )
            asks_completion = any(token in query_text.lower() for token in ("completed", "complete", "done", "finish", "finished"))
            if work_next_person:
                if work_next_items:
                    query_answer = (
                        f"{work_next_person} should work on {len(work_next_items)} task(s): "
                        f"{', '.join(item.title for item in work_next_items[:10])}."
                    )
                else:
                    inferred = [
                        item
                        for item in ranked_relevant
                        if not bool(item.done)
                        and self._is_semantic_list_match_for_person(
                            list_name=item.list_name,
                            person_name=work_next_person,
                            team_names=work_next_team_names,
                        )
                    ]
                    if inferred:
                        query_answer = (
                            f"No directly assigned or team-linked open tasks found for {work_next_person}. "
                            f"Suggested next tasks: {', '.join(item.title for item in inferred[:8])}."
                        )
                    else:
                        fallback_open = semantic_fallback_items[:8]
                        if fallback_open:
                            query_answer = (
                                f"No directly assigned or team-linked open tasks found for {work_next_person}. "
                                f"Suggested next tasks from semantically related lists/projects: {', '.join(item.title for item in fallback_open)}."
                            )
                        else:
                            query_answer = f"No open tasks found for {work_next_person} from assignment, ownership, team-linked projects, or semantically related lists/projects."
            if query_answer is None and asks_chores_left:
                chores_left = [item for item in ranked_relevant if not bool(item.done) and self._is_girls_chores_list(item.list_name)]
                if chores_left:
                    query_answer = f"The girls have {len(chores_left)} chore(s) left: {', '.join(item.title for item in chores_left[:8])}."
                else:
                    query_answer = "The girls have no unfinished chores."
            if query_answer is None and ranked_relevant and asks_completion:
                top = next((item for item in ranked_relevant if not item.title.strip().endswith("?")), ranked_relevant[0])
                if top.done:
                    query_answer = f"Yes. '{top.title}' is complete."
                else:
                    query_answer = f"No. '{top.title}' is not complete."
            elif query_answer is None and ranked_relevant:
                top = ", ".join(item.title for item in ranked_relevant[:5])
                query_answer = f"{subject} has {len(ranked_relevant)} relevant task(s): {top}."
            elif query_answer is None:
                query_answer = f"{subject} has no relevant tasks for that inquiry."

        return TaskInsights(
            generated_at=now,
            overview=InsightOverview(total_lists=len(lists), total_open_tasks=total_open, total_done_tasks=total_done, overdue_tasks=len(overdue)),
            due_soon=due_soon[:10],
            overdue=overdue[:10],
            stale=stale[:10],
            relevant_tasks=sorted(
                relevant,
                key=lambda item: self._relevance_score(
                    title=item.title,
                    list_name=item.list_name,
                    topic=focus_topic,
                    person=focus_person,
                    terms=focus_terms,
                    query_text=query_text,
                ),
                reverse=True,
            )[:20],
            query_topic=focus_topic,
            query_terms=focus_terms,
            query_answer=query_answer,
            at_risk_projects=[item.list_name for item in overdue[:5] if item.list_name],
            recommendations=recommendations,
            all_projects=deterministic_rows if asks_get_all_projects else [],
            all_tasks=deterministic_rows if asks_get_all_tasks else [],
        )

    def _relevance_score(
        self,
        *,
        title: str,
        list_name: str,
        topic: str | None,
        person: str | None,
        terms: list[str],
        query_text: str,
    ) -> float:
        if topic != "general_query":
            return 0.0
        haystack = f"{title} {list_name}".lower()
        score = _similarity(query_text, haystack)
        query_norm = re.sub(r"[^a-z0-9 ]+", "", query_text.lower()).strip()
        title_norm = re.sub(r"[^a-z0-9 ]+", "", title.lower()).strip()
        if title.strip().endswith("?"):
            score *= 0.55
        if query_norm and title_norm and query_norm == title_norm:
            score *= 0.4
        if terms:
            overlap = sum(1 for term in terms if term in haystack) / max(len(terms), 1)
            score = max(score, overlap)
        return score

    def _apply_query_override(self, insights: TaskInsights, override: str | None) -> TaskInsights:
        if not override:
            return insights
        insights.query_answer = override
        return insights

    def _extract_work_next_person(self, query_text: str) -> str | None:
        clean = query_text.strip()
        patterns = [
            r"\bwhat\s+tasks\s+should\s+([a-z][a-z' -]{1,40})\s+work\s+next\b",
            r"\bwhat\s+should\s+([a-z][a-z' -]{1,40})\s+work\s+on\s+next\b",
            r"\bwhat\s+should\s+([a-z][a-z' -]{1,40})\s+do\s+next\b",
        ]
        match = None
        for pattern in patterns:
            match = re.search(pattern, clean, flags=re.IGNORECASE)
            if match:
                break
        if not match:
            return None
        return match.group(1).strip().title()

    def _is_project_listing_query(self, query_text: str) -> bool:
        text = query_text.strip().lower()
        if not text:
            return False
        patterns = [
            r"^\s*list\s+(all\s+)?(projects|lists)\b",
            r"^\s*show(\s+me)?\s+(all\s+)?(projects|lists)\b",
            r"^\s*what\s+are\s+(my\s+)?(projects|lists)\b",
            r"^\s*what\s+(projects|lists)\s+do\s+i\s+have\b",
        ]
        return any(re.search(pattern, text) for pattern in patterns)

    def _is_get_all_projects_query(self, query_text: str) -> bool:
        text = query_text.strip().lower()
        if not text:
            return False
        return bool(re.search(r"\bget_all_projects\b", text))

    def _is_get_all_tasks_query(self, query_text: str) -> bool:
        text = query_text.strip().lower()
        if not text:
            return False
        return bool(re.search(r"\bget_all_tasks\b", text))

    def _is_team_listing_query(self, query_text: str) -> bool:
        text = query_text.strip().lower()
        if not text:
            return False
        patterns = [
            r"^\s*list\s+(all\s+)?teams?\b",
            r"^\s*show(\s+me)?\s+(all\s+)?teams?\b",
            r"^\s*what\s+teams?\s+do\s+i\s+have\b",
        ]
        return any(re.search(pattern, text) for pattern in patterns)

    def _extract_team_members_target(self, query_text: str) -> str | None:
        text = query_text.strip()
        if not text:
            return None
        patterns = [
            r"\b(?:list|show)\s+(?:all\s+)?members(?:\s+in|\s+of)?\s+(?:the\s+)?(.+?)\s+team\b",
            r"\bwho\s+is\s+in\s+(?:the\s+)?(.+?)\s+team\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                target = str(match.group(1) or "").strip(" .")
                if target:
                    return target
        return None

    def _is_archived_projects_listing_query(self, query_text: str) -> bool:
        text = query_text.strip().lower()
        if not text:
            return False
        return bool(re.search(r"\b(list|show)\b.*\barchived\b.*\b(project|projects|lists)\b", text))

    def _extract_label_task_query_label(self, query_text: str) -> str | None:
        text = query_text.strip()
        if not text:
            return None
        patterns = [
            r"\b(?:list|show)\s+(?:all\s+)?tasks?\s+label(?:ed)?\s+(.+)$",
            r"\bwhat\s+tasks?\s+are\s+label(?:ed)?\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                label = str(match.group(1) or "").strip(" .\"'")
                if label:
                    return label
        return None

    def _find_team_by_name(self, requested_name: str, *, tools: TaskTools) -> dict[str, Any] | None:
        requested = requested_name.strip().lower()
        if not requested:
            return None
        teams = self._safe_list_teams(tools)
        best: tuple[float, dict[str, Any]] | None = None
        for team in teams:
            name = str(team.get("name") or "").strip()
            if not name:
                continue
            lower = name.lower()
            score = 1.0 if lower == requested else _similarity(requested, lower)
            if requested in lower:
                score = max(score, 0.94)
            if best is None or score > best[0]:
                best = (score, team)
        if best and best[0] >= 0.55:
            return best[1]
        return None

    def _unique_user_rows(self, rows: list[dict[str, Any]]) -> list[str]:
        seen_ids: set[int] = set()
        seen_names: set[str] = set()
        out: list[str] = []
        for row in rows:
            user_id = _int_or_none(row.get("id"))
            name = str(row.get("name") or row.get("username") or row.get("email") or "").strip()
            if not name:
                continue
            lname = name.lower()
            if user_id is not None:
                if user_id in seen_ids:
                    continue
                seen_ids.add(user_id)
            elif lname in seen_names:
                continue
            seen_names.add(lname)
            out.append(name)
        out.sort(key=str.lower)
        return out

    def _tasks_with_label(
        self,
        *,
        label_name: str,
        lists: list[dict[str, Any]],
        all_tasks_by_list: dict[int, list[dict[str, Any]]],
    ) -> list[str]:
        requested = label_name.strip().lower()
        if not requested:
            return []
        rows: list[str] = []
        for list_item in lists:
            list_id = _int_or_none(list_item.get("id"))
            list_name = str(list_item.get("title") or "").strip() or "Untitled"
            tasks = all_tasks_by_list.get(list_id or -1, [])
            for task in tasks:
                labels = task.get("labels") if isinstance(task.get("labels"), list) else []
                label_titles = [str(item.get("title") or "").strip() for item in labels if isinstance(item, dict)]
                matched = False
                for title in label_titles:
                    clean = title.lower()
                    if not clean:
                        continue
                    score = _similarity(requested, clean)
                    if clean == requested or requested in clean or score >= 0.78:
                        matched = True
                        break
                if matched:
                    task_title = str(task.get("title") or "").strip()
                    if task_title:
                        rows.append(f"{task_title} [{list_name}]")
        return rows

    def _project_rows(
        self,
        *,
        lists: list[dict[str, Any]],
        all_tasks_by_list: dict[int, list[dict[str, Any]]],
        include_archived: bool,
        archived_only: bool = False,
    ) -> list[str]:
        rows: list[str] = []
        for item in lists:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            is_archived = bool(item.get("is_archived"))
            if archived_only and not is_archived:
                continue
            if is_archived and not include_archived:
                continue
            list_id = _int_or_none(item.get("id"))
            tasks = all_tasks_by_list.get(list_id or -1, [])
            open_count = sum(1 for task in tasks if not bool(task.get("done")))
            parent = None
            for key in ("parent_project", "parent_project_id", "parent_id"):
                value = item.get(key)
                if isinstance(value, dict):
                    parent = str(value.get("title") or value.get("name") or "").strip() or None
                    break
                if value is not None:
                    maybe_parent = _int_or_none(value)
                    if maybe_parent is not None and maybe_parent <= 0:
                        parent = None
                    else:
                        parent = str(value).strip() or None
                    break
            row = f"{title} ({open_count} open)"
            if parent:
                row += f" under {parent}"
            if is_archived:
                row += " [archived]"
            rows.append(row)
        rows.sort(key=str.lower)
        return rows

    def _deterministic_project_rows(self, lists: list[dict[str, Any]], *, tools: TaskTools) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in lists:
            list_id = _int_or_none(item.get("id"))
            if list_id is None:
                continue
            name = str(item.get("title") or "").strip()
            parent_raw = item.get("parent_project_id")
            if parent_raw is None and isinstance(item.get("parent_project"), dict):
                parent_raw = item.get("parent_project", {}).get("id")
            if parent_raw is None:
                parent_raw = item.get("parent_id")
            parent_id = _int_or_none(parent_raw)
            if parent_id is not None and parent_id <= 0:
                parent_id = None
            tasks = self._safe_list_tasks(tools, list_id)
            open_task_count = sum(1 for task in tasks if not bool(task.get("done")))
            rows.append(
                {
                    "id": int(list_id),
                    "name": name,
                    "parent_id": parent_id,
                    "open_task_count": int(open_task_count),
                    "archived": bool(item.get("is_archived")),
                }
            )
        rows.sort(key=lambda row: (int(row["id"]), str(row["name"]).lower()))
        return rows

    def _contains_destructive_admin_actions(
        self,
        *,
        bulk_actions: list[dict[str, str]],
        management_actions: list[dict[str, str]],
    ) -> bool:
        if any(str(action.get("action") or "") == "clear_tasks" for action in bulk_actions):
            return True
        destructive_management = {"delete_projects", "archive_projects", "move_tasks"}
        return any(str(action.get("action") or "") in destructive_management for action in management_actions)

    def _is_semantic_list_match_for_person(self, *, list_name: str, person_name: str | None, team_names: set[str]) -> bool:
        hay = re.sub(r"[^a-z0-9 ]+", "", list_name.lower()).strip()
        if not hay:
            return False
        needles: list[str] = []
        if person_name:
            needles.append(person_name)
        needles.extend(sorted(team_names))
        for label in needles:
            clean = re.sub(r"[^a-z0-9 ]+", "", str(label).lower()).strip()
            if not clean:
                continue
            if clean in hay or _similarity(clean, hay) >= 0.62:
                return True
            tokens = [
                tok
                for tok in clean.split()
                if len(tok) >= 3 and tok not in {"project", "projects", "team", "teams", "parent", "family", "group", "list", "lists"}
            ]
            if any(tok in hay for tok in tokens):
                return True
        return False

    def _resolve_user_ids_by_name(
        self,
        *,
        requested_name: str,
        tools: TaskTools,
        lists: list[dict[str, Any]],
        all_tasks_by_list: dict[int, list[dict[str, Any]]],
    ) -> set[int]:
        requested = requested_name.strip().lower()
        if not requested:
            return set()
        candidates: list[dict[str, Any]] = []
        seen: set[int] = set()

        def _add(candidate: dict[str, Any] | None) -> None:
            if not isinstance(candidate, dict):
                return
            cid = _int_or_none(candidate.get("id"))
            if cid is None or cid in seen:
                return
            seen.add(cid)
            candidates.append(candidate)

        _add(tools.get_current_user())
        for item in lists:
            _add(item.get("owner") if isinstance(item, dict) else None)
        for tasks in all_tasks_by_list.values():
            for task in tasks:
                _add(task.get("created_by") if isinstance(task, dict) else None)
                for assignee in (task.get("assignees") or []):
                    if isinstance(assignee, dict):
                        _add(assignee)
        for team in self._safe_list_teams(tools):
            tid = _int_or_none(team.get("id"))
            if tid is None:
                continue
            members = self._safe_list_team_members(tools, tid)
            embedded_members = team.get("members") if isinstance(team.get("members"), list) else []
            for member in [*members, *embedded_members]:
                _add(member if isinstance(member, dict) else None)

        matched: set[int] = set()
        best_score = 0.0
        for item in candidates:
            cid = _int_or_none(item.get("id"))
            if cid is None:
                continue
            label = " ".join(
                str(part).strip() for part in [item.get("name"), item.get("username"), item.get("email")] if part is not None and str(part).strip()
            ).lower()
            score = _similarity(requested, label)
            if requested in label:
                score = max(score, 0.95)
            if score > best_score:
                best_score = score
            if score >= 0.45:
                matched.add(cid)
        if matched:
            return matched
        if best_score > 0:
            best: tuple[float, int] | None = None
            for item in candidates:
                cid = _int_or_none(item.get("id"))
                if cid is None:
                    continue
                label = " ".join(
                    str(part).strip() for part in [item.get("name"), item.get("username"), item.get("email")] if part is not None and str(part).strip()
                ).lower()
                score = _similarity(requested, label)
                if best is None or score > best[0]:
                    best = (score, cid)
            if best is not None and best[0] >= 0.3:
                return {best[1]}
        return set()

    def _split_named_targets(self, text: str) -> list[str]:
        if not text.strip():
            return []
        chunks = re.split(r",| and ", text)
        return [part.strip(" .\t") for part in chunks if part.strip(" .\t")]

    def _clean_action_target(self, text: str) -> str:
        value = str(text or "").strip()
        value = re.sub(r"^(replace|update|label)\s+", "", value, flags=re.IGNORECASE)
        value = re.sub(r"^(the|a|an)\s+", "", value, flags=re.IGNORECASE)
        return value.strip(" .")

    def _highest_priority_open_task(
        self,
        list_ids: list[int],
        all_tasks_by_list: dict[int, list[dict[str, Any]]],
        lists: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any]] | None:
        list_name_by_id = {int(item.get("id")): str(item.get("title") or "") for item in lists if item.get("id") is not None}
        best: tuple[int, dict[str, Any]] | None = None
        best_score: tuple[int, float] = (-1, -1.0)
        for list_id in list_ids:
            for task in all_tasks_by_list.get(list_id, []):
                if bool(task.get("done")):
                    continue
                priority = int(task.get("priority") or 0)
                title = str(task.get("title") or "")
                lexical = _similarity(title, title)
                score = (priority, lexical)
                if score > best_score:
                    best_score = score
                    best = (list_id, task)
        if best is None:
            return None
        return list_name_by_id.get(best[0], str(best[0])), best[1]

    def _match_task_by_text(
        self,
        target: str,
        *,
        all_tasks_by_list: dict[int, list[dict[str, Any]]],
        restrict_list_ids: list[int] | None = None,
    ) -> tuple[int, dict[str, Any]] | None:
        def _norm(value: str) -> str:
            value = re.sub(r"[^a-z0-9 ]+", "", value.lower()).strip()
            tokens = []
            for token in value.split():
                if token.endswith("s") and len(token) > 3:
                    token = token[:-1]
                tokens.append(token)
            return " ".join(tokens)

        def _token_overlap(a: str, b: str) -> float:
            ta = set(_norm(a).split())
            tb = set(_norm(b).split())
            if not ta or not tb:
                return 0.0
            return len(ta & tb) / max(len(ta | tb), 1)

        best: tuple[int, dict[str, Any]] | None = None
        best_score = 0.0
        allowed = set(restrict_list_ids or [])
        for list_id, tasks in all_tasks_by_list.items():
            if allowed and list_id not in allowed:
                continue
            for task in tasks:
                title = str(task.get("title") or "")
                if not title:
                    continue
                score = max(_similarity(target, title), _token_overlap(target, title))
                if score > best_score:
                    best_score = score
                    best = (list_id, task)
        if best is None or best_score < 0.32:
            return None
        return best

    def _match_tasks_by_text(
        self,
        target: str,
        *,
        all_tasks_by_list: dict[int, list[dict[str, Any]]],
    ) -> list[tuple[int, dict[str, Any]]]:
        target_norm = re.sub(r"[^a-z0-9 ]+", "", target.lower()).strip()
        target_tokens = {tok for tok in target_norm.split() if tok not in {"task", "tasks", "the", "a", "an"}}
        if not target_tokens:
            return []
        matched: list[tuple[int, dict[str, Any]]] = []
        for list_id, tasks in all_tasks_by_list.items():
            for task in tasks:
                title = str(task.get("title") or "")
                if not title:
                    continue
                title_norm = re.sub(r"[^a-z0-9 ]+", "", title.lower()).strip()
                title_tokens = set(title_norm.split())
                overlap_count = len(target_tokens & title_tokens)
                overlap = overlap_count / max(len(target_tokens), 1)
                lexical = _similarity(target_norm, title_norm)
                # Guard against unrelated fuzzy matches: require either token overlap
                # or a very strong lexical match.
                if overlap_count <= 0 and lexical < 0.86 and target_norm not in title_norm:
                    continue
                score = max(lexical, overlap)
                if target_norm in title_norm:
                    score = max(score, 0.95)
                if overlap >= 0.5 or score >= 0.86:
                    matched.append((list_id, task))
        return matched

    def _reconcile_purchase_items(
        self,
        purchase_items: list[str],
        all_tasks_by_list: dict[int, list[dict[str, Any]]],
        tools: TaskTools,
    ) -> dict[str, Any]:
        executed: list[ExecutionOperationResult] = []
        failed: list[ExecutionOperationResult] = []
        trace: list[dict[str, Any]] = []
        completed_ids: list[int] = []

        all_open_tasks: list[tuple[int, dict[str, Any]]] = []
        for list_id, tasks in all_tasks_by_list.items():
            for task in tasks:
                if not bool(task.get("done")):
                    all_open_tasks.append((list_id, task))

        for item in purchase_items:
            best_score = 0.0
            best_task: tuple[int, dict[str, Any]] | None = None
            for list_id, task in all_open_tasks:
                score = _similarity(item, str(task.get("title") or ""))
                if score > best_score:
                    best_score = score
                    best_task = (list_id, task)
            if best_task is None:
                continue
            if best_score < task_settings.task_agent_reconcile_ambiguous_threshold:
                continue
            task_id = _int_or_none(best_task[1].get("id"))
            if task_id is None:
                continue
            op = PlannedOperation(
                type="complete_task",
                payload={"task_id": task_id, "matched_item": item, "score": round(best_score, 3)},
                reason="Purchase-like evidence matched existing task",
                confidence=min(1.0, max(task_settings.task_agent_reconcile_ambiguous_threshold, best_score)),
            )
            result = self._execute_operation(op, tools, [])
            trace.append({"operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})
            if result.ok and best_score >= task_settings.task_agent_reconcile_autocomplete_threshold:
                executed.append(result)
                completed_ids.append(task_id)
            elif result.ok:
                # Aggressive mode still commits ambiguous matches.
                executed.append(result)
                completed_ids.append(task_id)
            else:
                failed.append(result)
        return {"executed": executed, "failed": failed, "trace": trace, "completed_task_ids": completed_ids}

    def _extract_attachment_text(self, attachments: list[Any]) -> str:
        extracted: list[str] = []
        for item in attachments:
            name = str(getattr(item, "name", "") or "")
            b64 = getattr(item, "bytes_base64", None)
            content_type = str(getattr(item, "type", "") or "")
            if not b64:
                continue
            try:
                raw = base64.b64decode(b64, validate=False)
            except Exception:
                continue
            if content_type.startswith("text/") or name.lower().endswith((".txt", ".md", ".csv", ".json", ".log")):
                for encoding in ("utf-8", "latin-1"):
                    try:
                        extracted.append(raw.decode(encoding))
                        break
                    except Exception:
                        continue
            else:
                # For binary attachments we keep metadata as weak context.
                extracted.append(name)
        return "\n".join(part for part in extracted if part.strip())

    def _safe_capabilities(self, tools: TaskTools) -> dict[str, bool]:
        try:
            return tools.capabilities()
        except Exception:
            return {}

    def _normalize_candidate_dates(self, *, item: ExtractedTask, metadata: dict[str, Any]) -> tuple[dict[str, str | None], list[str]]:
        tz_name = str(metadata.get("timezone") or metadata.get("tz") or task_settings.task_agent_default_timezone).strip() or "UTC"
        try:
            tzinfo = ZoneInfo(tz_name)
        except Exception:
            tzinfo = UTC
        now = datetime.now(tzinfo)
        out: dict[str, str | None] = {"due_date": None, "start_date": None, "end_date": None}
        issues: list[str] = []
        for key, raw in (("start_date", item.start_date), ("end_date", item.end_date), ("due_date", item.due_date)):
            parsed = self._parse_date_phrase(raw, now=now, tzinfo=tzinfo)
            out[key] = parsed
            if raw and not parsed:
                issues.append(f"Task '{item.title}' has an ambiguous {key.replace('_', ' ')}: '{raw}'.")
        start = out.get("start_date")
        end = out.get("end_date")
        due = out.get("due_date")
        if start and end and start > end:
            issues.append(f"Task '{item.title}' has start date after end date.")
        if start and due and due < start:
            issues.append(f"Task '{item.title}' has due date before start date.")
        if end and not due:
            out["due_date"] = end
        return out, issues

    def _parse_date_phrase(self, value: str | None, *, now: datetime, tzinfo: Any) -> str | None:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
            return f"{text}T00:00:00+00:00"
        if re.match(r"^\d{4}-\d{2}-\d{2}T", text):
            return text
        lowered = text.lower()
        if lowered in {"today", "tonight"}:
            dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return dt.astimezone(UTC).isoformat()
        if lowered == "tomorrow":
            dt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return dt.astimezone(UTC).isoformat()
        weekday_map = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        m = re.search(r"\b(?:next|this)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lowered)
        if m:
            target = weekday_map[m.group(1)]
            delta = (target - now.weekday()) % 7
            if "next" in lowered and delta == 0:
                delta = 7
            dt = (now + timedelta(days=delta)).replace(hour=0, minute=0, second=0, microsecond=0)
            return dt.astimezone(UTC).isoformat()
        # Lightweight explicit format support without extra dependency.
        m2 = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", text)
        if m2:
            month = int(m2.group(1))
            day = int(m2.group(2))
            year = int(m2.group(3)) if m2.group(3) else now.year
            if year < 100:
                year += 2000
            try:
                dt = datetime(year, month, day, tzinfo=tzinfo).replace(hour=0, minute=0, second=0, microsecond=0)
                return dt.astimezone(UTC).isoformat()
            except Exception:
                return None
        return None

    def _apply_advanced_task_features(
        self,
        *,
        task_id: int,
        task: ExtractedTask,
        list_id: int,
        tools: TaskTools,
        lists: list[dict[str, Any]],
        capabilities: dict[str, bool],
        all_tasks_by_list: dict[int, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        executed: list[ExecutionOperationResult] = []
        failed: list[ExecutionOperationResult] = []
        trace: list[dict[str, Any]] = []
        artifacts: dict[str, list[int]] = {
            "assignee_task_ids": [],
            "labeled_task_ids": [],
            "progress_task_ids": [],
            "color_task_ids": [],
            "repeat_task_ids": [],
            "related_task_ids": [],
            "attachment_task_ids": [],
            "moved_task_ids": [],
            "priority_task_ids": [],
        }

        if task.assignees:
            assignee_ids: set[int] = set()
            for assignee in task.assignees:
                assignee_ids.update(
                    self._resolve_user_ids_by_name(
                        requested_name=assignee,
                        tools=tools,
                        lists=lists,
                        all_tasks_by_list=all_tasks_by_list,
                    )
                )
            if assignee_ids:
                op = PlannedOperation(
                    type="set_task_assignees",
                    payload={"task_id": task_id, "assignee_ids": sorted(assignee_ids)},
                    reason="Set extracted assignees",
                    confidence=max(0.65, task.confidence),
                )
                result = self._execute_operation(op, tools, lists)
                trace.append({"operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})
                if result.ok:
                    executed.append(result)
                    artifacts["assignee_task_ids"].append(task_id)
                else:
                    failed.append(result)

        if task.labels:
            for label_name in task.labels:
                op_label = PlannedOperation(type="ensure_label", payload={"title": label_name}, reason="Ensure label from extracted task", confidence=0.8)
                label_result = self._execute_operation(op_label, tools, lists)
                trace.append({"operation": op_label.model_dump(mode="json"), "result": label_result.model_dump(mode="json")})
                if not (label_result.ok and label_result.result and label_result.result.get("id") is not None):
                    failed.append(label_result)
                    continue
                attach = PlannedOperation(
                    type="add_label_to_task",
                    payload={"task_id": task_id, "label_id": int(label_result.result["id"])},
                    reason="Attach extracted label to task",
                    confidence=0.8,
                )
                attach_result = self._execute_operation(attach, tools, lists)
                trace.append({"operation": attach.model_dump(mode="json"), "result": attach_result.model_dump(mode="json")})
                if attach_result.ok:
                    executed.append(attach_result)
                    artifacts["labeled_task_ids"].append(task_id)
                else:
                    failed.append(attach_result)

        if task.progress is not None:
            if capabilities.get("progress", False):
                op = PlannedOperation(type="set_task_progress", payload={"task_id": task_id, "progress": task.progress}, reason="Set extracted progress", confidence=0.75)
                result = self._execute_operation(op, tools, lists)
                trace.append({"operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})
                if result.ok:
                    executed.append(result)
                    artifacts["progress_task_ids"].append(task_id)
                else:
                    failed.append(result)
            else:
                task.labels.append(f"progress:{int(max(0, min(task.progress, 100)))}%")

        if task.color:
            if capabilities.get("color", False):
                op = PlannedOperation(type="set_task_color", payload={"task_id": task_id, "color": task.color}, reason="Set extracted color", confidence=0.75)
                result = self._execute_operation(op, tools, lists)
                trace.append({"operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})
                if result.ok:
                    executed.append(result)
                    artifacts["color_task_ids"].append(task_id)
                else:
                    failed.append(result)
            else:
                task.labels.append(f"color:{task.color}")

        if task.repeat_interval:
            repeat_seconds = self._parse_repeat_interval_seconds(task.repeat_interval)
            if repeat_seconds is not None:
                op = PlannedOperation(
                    type="set_task_repeat",
                    payload={"task_id": task_id, "repeat_after_seconds": repeat_seconds},
                    reason="Set extracted repeating interval",
                    confidence=0.72,
                )
                result = self._execute_operation(op, tools, lists)
                trace.append({"operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})
                if result.ok:
                    executed.append(result)
                    artifacts["repeat_task_ids"].append(task_id)
                else:
                    failed.append(result)

        if task.relations:
            for rel in task.relations:
                target_text = str(rel.get("target") or rel.get("task") or "").strip()
                if not target_text:
                    continue
                match = self._match_task_by_text(target_text, all_tasks_by_list=all_tasks_by_list)
                if not match:
                    continue
                _, other_task = match
                other_id = _int_or_none(other_task.get("id"))
                if other_id is None:
                    continue
                relation_type = str(rel.get("type") or task_settings.task_agent_relation_default).strip() or task_settings.task_agent_relation_default
                op = PlannedOperation(
                    type="add_task_relation",
                    payload={"task_id": task_id, "other_task_id": int(other_id), "relation_type": relation_type},
                    reason="Add extracted task relationship",
                    confidence=0.7,
                )
                result = self._execute_operation(op, tools, lists)
                trace.append({"operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})
                if result.ok:
                    executed.append(result)
                    artifacts["related_task_ids"].append(task_id)
                else:
                    failed.append(result)

        if task.attachments:
            for attachment in task.attachments:
                op = PlannedOperation(
                    type="add_task_attachment",
                    payload={
                        "task_id": task_id,
                        "url": attachment.get("url"),
                        "filename": attachment.get("filename") or attachment.get("name"),
                        "bytes_base64": attachment.get("bytes_base64"),
                    },
                    reason="Attach extracted task attachment",
                    confidence=0.7,
                )
                result = self._execute_operation(op, tools, lists)
                trace.append({"operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})
                if result.ok:
                    executed.append(result)
                    artifacts["attachment_task_ids"].append(task_id)
                else:
                    failed.append(result)

        if task.target_project:
            ids = self._resolve_target_list_ids(task.target_project, lists)
            if ids and ids[0] != list_id:
                op = PlannedOperation(type="move_task", payload={"task_id": task_id, "project_id": int(ids[0])}, reason="Move task to extracted target project", confidence=0.72)
                result = self._execute_operation(op, tools, lists)
                trace.append({"operation": op.model_dump(mode="json"), "result": result.model_dump(mode="json")})
                if result.ok:
                    executed.append(result)
                    artifacts["moved_task_ids"].append(task_id)
                else:
                    failed.append(result)
        return {"executed": executed, "failed": failed, "trace": trace, "artifacts": artifacts}

    def _parse_repeat_interval_seconds(self, value: str) -> int | None:
        text = value.strip().lower()
        if not text:
            return None
        m = re.search(r"\bevery\s+(\d+)\s+(day|days|week|weeks|month|months)\b", text)
        if m:
            count = int(m.group(1))
            unit = m.group(2)
        elif "every day" in text:
            count, unit = 1, "day"
        elif "every week" in text:
            count, unit = 1, "week"
        elif "every month" in text:
            count, unit = 1, "month"
        else:
            return None
        factor = 86400
        if unit.startswith("week"):
            factor = 7 * 86400
        elif unit.startswith("month"):
            factor = 30 * 86400
        return count * factor

    def _best_project_similarity(self, candidate_title: str, lists: list[dict[str, Any]]) -> float:
        best = 0.0
        for item in lists:
            current = str(item.get("title") or "")
            best = max(best, _similarity(candidate_title, current))
        return best

    def _find_existing_list_id(self, candidate_title: str, lists: list[dict[str, Any]]) -> int | None:
        target = re.sub(r"[^a-z0-9 ]+", "", candidate_title.lower()).strip()
        for item in lists:
            current = str(item.get("title") or "")
            current_norm = re.sub(r"[^a-z0-9 ]+", "", current.lower()).strip()
            if not current_norm:
                continue
            if current_norm == target or _similarity(current_norm, target) >= 0.92:
                try:
                    return int(item.get("id"))
                except Exception:
                    return None
        return None

    def _safe_list_lists(self, tools: TaskTools) -> list[dict[str, Any]]:
        try:
            return tools.list_lists()
        except Exception:
            return []

    def _safe_list_tasks(self, tools: TaskTools, list_id: int) -> list[dict[str, Any]]:
        try:
            return tools.list_tasks(list_id)
        except Exception:
            return []

    def _safe_list_teams(self, tools: TaskTools) -> list[dict[str, Any]]:
        try:
            return tools.list_teams()
        except Exception:
            return []

    def _safe_list_team_members(self, tools: TaskTools, team_id: int) -> list[dict[str, Any]]:
        try:
            return tools.list_team_members(team_id)
        except Exception:
            return []

    def _safe_list_list_teams(self, tools: TaskTools, list_id: int) -> list[dict[str, Any]]:
        try:
            return tools.list_list_teams(list_id)
        except Exception:
            return []

    def _has_similar_title(self, title: str, existing_titles: list[str]) -> bool:
        for current in existing_titles:
            if _similarity(title, current) >= 0.9:
                return True
        return False

    def _resolve_target_list_ids(self, target: str, lists: list[dict[str, Any]]) -> list[int]:
        norm_target = self._normalize_list_target(target)
        if not norm_target:
            return []
        by_id: dict[int, dict[str, Any]] = {}
        for item in lists:
            lid = _int_or_none(item.get("id"))
            if lid is not None:
                by_id[lid] = item
        target_tokens = set(norm_target.split())
        scored: list[tuple[float, int]] = []
        for item in lists:
            lid = _int_or_none(item.get("id"))
            if lid is None:
                continue
            search_text = self._list_search_text(item=item, by_id=by_id)
            search_tokens = set(search_text.split())
            score = max(
                _similarity(norm_target, search_text),
                len(target_tokens & search_tokens) / max(len(target_tokens | search_tokens), 1),
            )
            if norm_target in search_text:
                score = max(score, 0.9)
            if target_tokens and target_tokens.issubset(search_tokens):
                score = max(score, 0.94)
            if score >= 0.62:
                scored.append((score, lid))
        scored.sort(key=lambda it: it[0], reverse=True)
        return [lid for _, lid in scored[:3]]

    def _resolve_target_list_ids_from_tasks(
        self,
        target: str,
        *,
        lists: list[dict[str, Any]],
        all_tasks_by_list: dict[int, list[dict[str, Any]]],
    ) -> list[int]:
        norm_target = self._normalize_list_target(target)
        if not norm_target:
            return []
        by_id: dict[int, dict[str, Any]] = {}
        for item in lists:
            lid = _int_or_none(item.get("id"))
            if lid is None:
                continue
            by_id[lid] = item
        target_tokens = set(norm_target.split())
        scored: list[tuple[float, int]] = []
        for list_id, tasks in all_tasks_by_list.items():
            best = 0.0
            for task in tasks:
                task_title = str(task.get("title") or "")
                if not task_title:
                    continue
                score = _similarity(norm_target, task_title)
                if norm_target in re.sub(r"[^a-z0-9 ]+", "", task_title.lower()):
                    score = max(score, 0.9)
                if score > best:
                    best = score
            if best <= 0:
                continue
            list_item = by_id.get(list_id, {"id": list_id, "title": ""})
            list_search = self._list_search_text(item=list_item, by_id=by_id)
            list_tokens = set(list_search.split())
            list_boost = max(
                _similarity(norm_target, list_search),
                len(target_tokens & list_tokens) / max(len(target_tokens | list_tokens), 1),
            )
            if target_tokens and target_tokens.issubset(list_tokens):
                list_boost = max(list_boost, 0.94)
            scored.append((max(best, list_boost), list_id))
        scored = [item for item in scored if item[0] >= 0.62]
        scored.sort(key=lambda it: it[0], reverse=True)
        return [lid for _, lid in scored[:3]]

    def _normalize_list_target(self, target: str) -> str:
        norm_target = re.sub(r"[^a-z0-9 ]+", "", target.lower()).strip()
        norm_target = re.sub(r"\b(project|projects|list|lists)\b", "", norm_target).strip()
        return re.sub(r"\s+", " ", norm_target).strip()

    def _list_search_text(self, *, item: dict[str, Any], by_id: dict[int, dict[str, Any]]) -> str:
        title = re.sub(r"[^a-z0-9 ]+", "", str(item.get("title") or "").lower()).strip()
        if not title:
            return ""
        parts = [title]
        parent_id = _int_or_none(item.get("parent_project_id"))
        seen: set[int] = set()
        depth = 0
        while parent_id and parent_id not in seen and depth < 4:
            seen.add(parent_id)
            parent = by_id.get(parent_id)
            if not parent:
                break
            parent_title = re.sub(r"[^a-z0-9 ]+", "", str(parent.get("title") or "").lower()).strip()
            if parent_title:
                parts.append(parent_title)
            parent_id = _int_or_none(parent.get("parent_project_id"))
            depth += 1
        combined = " ".join(parts)
        return re.sub(r"\s+", " ", combined).strip()

    def _ensure_team(self, team_name: str, tools: TaskTools) -> tuple[int, bool] | None:
        clean = team_name.strip()
        if not clean:
            return None
        teams = []
        try:
            teams = tools.list_teams()
        except Exception:
            teams = []
        norm = re.sub(r"[^a-z0-9 ]+", "", clean.lower()).strip()
        best: tuple[float, int] | None = None
        for team in teams:
            tid = _int_or_none(team.get("id"))
            if tid is None:
                continue
            name = re.sub(r"[^a-z0-9 ]+", "", str(team.get("name") or "").lower()).strip()
            score = _similarity(norm, name)
            if norm and (norm == name or norm in name):
                score = 1.0
            if score >= 0.76 and (best is None or score > best[0]):
                best = (score, tid)
        if best is not None:
            return best[1], False
        try:
            created = tools.create_team(clean)
            tid = _int_or_none(created.get("id"))
            if tid is None:
                return None
            return tid, True
        except Exception:
            return None

    def _is_girls_chores_list(self, list_name: str) -> bool:
        name = list_name.lower()
        has_girls = "girls" in name or "girl" in name
        has_chores = "chore" in name
        return has_girls or (has_chores and "boys" not in name and "boy" not in name)

    def _is_similar_to_completed_match(
        self,
        title: str,
        all_tasks_by_list: dict[int, list[dict[str, Any]]],
        matched_completion_task_ids: set[int],
    ) -> bool:
        if not matched_completion_task_ids:
            return False
        for tasks in all_tasks_by_list.values():
            for task in tasks:
                task_id = _int_or_none(task.get("id"))
                if task_id is None or task_id not in matched_completion_task_ids:
                    continue
                if _similarity(title, str(task.get("title") or "")) >= 0.72:
                    return True
        return False

    def _match_existing_task_for_completion(
        self,
        *,
        update_target: str,
        all_tasks_by_list: dict[int, list[dict[str, Any]]],
    ) -> tuple[int, dict[str, Any]] | None:
        best: tuple[int, dict[str, Any]] | None = None
        best_score = 0.0
        for list_id, tasks in all_tasks_by_list.items():
            for task in tasks:
                title = str(task.get("title") or "")
                if not title:
                    continue
                score = _similarity(update_target, title)
                if score > best_score:
                    best_score = score
                    best = (list_id, task)
        if best is None or best_score < 0.56:
            return None
        return best

    def _resolve_assignee_id(
        self,
        *,
        requested_name: str,
        tools: TaskTools,
        actor_email: str,
        lists: list[dict[str, Any]],
        all_tasks_by_list: dict[int, list[dict[str, Any]]],
    ) -> int | None:
        candidates: list[dict[str, Any]] = []
        seen_ids: set[int] = set()

        def _add(candidate: dict[str, Any] | None) -> None:
            if not isinstance(candidate, dict):
                return
            cid = _int_or_none(candidate.get("id"))
            if cid is None or cid in seen_ids:
                return
            seen_ids.add(cid)
            candidates.append(candidate)

        _add(tools.get_current_user())
        for item in lists:
            _add(item.get("owner") if isinstance(item, dict) else None)
        for tasks in all_tasks_by_list.values():
            for task in tasks:
                _add(task.get("created_by") if isinstance(task, dict) else None)
                for assignee in (task.get("assignees") or []):
                    if isinstance(assignee, dict):
                        _add(assignee)

        requested_norm = requested_name.strip().lower()
        if not candidates:
            return None
        best_id = None
        best_score = 0.0
        for item in candidates:
            label = " ".join(
                str(part).strip() for part in [item.get("name"), item.get("username"), item.get("email")] if part is not None and str(part).strip()
            ).lower()
            score = _similarity(requested_norm, label)
            if score > best_score:
                best_score = score
                best_id = _int_or_none(item.get("id"))
        if best_id is not None and best_score >= 0.4:
            return best_id
        current = tools.get_current_user()
        return _int_or_none(current.get("id")) if isinstance(current, dict) else None


def _coerce_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", value):
        if len(value) == 10:
            return value + "T00:00:00+00:00"
        return value
    return None


def _similarity(a: str, b: str) -> float:
    norm_a = re.sub(r"[^a-z0-9 ]+", "", a.lower()).strip()
    norm_b = re.sub(r"[^a-z0-9 ]+", "", b.lower()).strip()
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0
    ratio = difflib.SequenceMatcher(a=norm_a, b=norm_b).ratio()
    tokens_a = set(norm_a.split())
    tokens_b = set(norm_b.split())
    overlap = len(tokens_a & tokens_b) / max(len(tokens_a | tokens_b), 1)
    return max(ratio, overlap)


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None
