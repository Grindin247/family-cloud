from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.config import settings


def latest_task_health_snapshot(*, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    lists = _list_projects()
    tasks_by_list: dict[int, list[dict[str, Any]]] = {}
    overdue: list[dict[str, Any]] = []
    due_soon: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    unassigned: list[dict[str, Any]] = []
    member_load: dict[str, dict[str, int]] = {}
    project_load: list[dict[str, Any]] = []

    total_open = 0
    total_done = 0

    for project in lists:
        project_id = _int_or_none(project.get("id"))
        if project_id is None:
            continue
        tasks = _list_tasks(project_id)
        tasks_by_list[project_id] = tasks
        project_open = 0
        project_overdue = 0
        project_stale = 0
        for task in tasks:
            done = bool(task.get("done"))
            due_date = _parse_dt(task.get("due_date"))
            updated_at = _parse_dt(task.get("updated") or task.get("updated_at") or task.get("created"))
            item = _task_item(task=task, project=project, due_date=due_date, done=done)
            if done:
                total_done += 1
            else:
                total_open += 1
                project_open += 1
            if not done and due_date:
                if due_date < current:
                    overdue.append(item)
                    project_overdue += 1
                elif due_date <= current + timedelta(days=3):
                    due_soon.append(item)
            if not done and updated_at and updated_at <= current - timedelta(days=settings.task_hygiene_stale_days):
                stale.append(item)
                project_stale += 1
            if not done and _looks_blocked(task):
                blocked.append(item)
            if not done and not [entry for entry in (task.get("assignees") or []) if isinstance(entry, dict)]:
                unassigned.append(item)
            if not done:
                for actor in _task_actor_keys(task, project):
                    bucket = member_load.setdefault(actor, {"open": 0, "overdue": 0, "due_soon": 0})
                    bucket["open"] += 1
                    if due_date and due_date < current:
                        bucket["overdue"] += 1
                    elif due_date and due_date <= current + timedelta(days=3):
                        bucket["due_soon"] += 1
        project_load.append(
            {
                "project_id": project_id,
                "project_name": str(project.get("title") or f"Project {project_id}"),
                "open_tasks": project_open,
                "overdue_tasks": project_overdue,
                "stale_tasks": project_stale,
            }
        )

    findings: list[dict[str, Any]] = []
    for item in overdue[:10]:
        findings.append(
            {
                "type": "task_overdue",
                "urgency": "critical",
                "summary": f"'{item['title']}' is overdue.",
                "topic": f"Overdue task: {item['title']}",
                "artifact_refs": _artifact_refs(item),
                "context": {"task_id": item["task_id"], "project_id": item["project_id"], "project_name": item["project_name"], "due_date": item["due_date"]},
                "dedupe_key": f"task_overdue:{item['task_id']}:{item['due_date']}",
            }
        )
    for item in due_soon[:10]:
        findings.append(
            {
                "type": "task_due_soon",
                "urgency": "high",
                "summary": f"'{item['title']}' is due soon.",
                "topic": f"Due soon task: {item['title']}",
                "artifact_refs": _artifact_refs(item),
                "context": {"task_id": item["task_id"], "project_id": item["project_id"], "project_name": item["project_name"], "due_date": item["due_date"]},
                "dedupe_key": f"task_due_soon:{item['task_id']}:{item['due_date']}",
            }
        )
    for item in stale[:10]:
        findings.append(
            {
                "type": "task_stale",
                "urgency": "medium",
                "summary": f"'{item['title']}' looks stale.",
                "topic": f"Stale task: {item['title']}",
                "artifact_refs": _artifact_refs(item),
                "context": {"task_id": item["task_id"], "project_id": item["project_id"], "project_name": item["project_name"]},
                "dedupe_key": f"task_stale:{item['task_id']}",
            }
        )
    for actor, counts in sorted(member_load.items(), key=lambda item: (-item[1]["open"], item[0])):
        if actor != "unassigned" and counts["open"] >= settings.task_hygiene_member_overload_open_tasks:
            findings.append(
                {
                    "type": "member_overload",
                    "urgency": "high",
                    "summary": f"{actor} has {counts['open']} open tasks.",
                    "topic": f"Task load high: {actor}",
                    "artifact_refs": [],
                    "context": {"actor_id": actor, "open_tasks": counts["open"], "overdue_tasks": counts["overdue"]},
                    "dedupe_key": f"task_overload:{actor}:{counts['open']}",
                }
            )
    for item in project_load:
        if item["overdue_tasks"] >= 3:
            findings.append(
                {
                    "type": "project_at_risk",
                    "urgency": "high",
                    "summary": f"{item['project_name']} has {item['overdue_tasks']} overdue tasks.",
                    "topic": f"At-risk project: {item['project_name']}",
                    "artifact_refs": [{"type": "project", "id": item["project_id"]}],
                    "context": item,
                    "dedupe_key": f"task_project_risk:{item['project_id']}:{item['overdue_tasks']}",
                }
            )

    return {
        "generated_at": current,
        "overview": {
            "total_lists": len(lists),
            "total_open_tasks": total_open,
            "total_done_tasks": total_done,
            "overdue_tasks": len(overdue),
            "due_soon_tasks": len(due_soon),
            "stale_tasks": len(stale),
            "unassigned_tasks": len(unassigned),
            "blocked_tasks": len(blocked),
        },
        "projects": lists,
        "tasks": tasks_by_list,
        "overdue": overdue[:25],
        "due_soon": due_soon[:25],
        "stale": stale[:25],
        "blocked": blocked[:25],
        "unassigned": unassigned[:25],
        "member_load": [
            {"actor_id": actor, "open_tasks": counts["open"], "overdue_tasks": counts["overdue"], "due_soon_tasks": counts["due_soon"]}
            for actor, counts in sorted(member_load.items(), key=lambda item: (-item[1]["open"], item[0]))
        ],
        "project_load": sorted(project_load, key=lambda item: (-item["open_tasks"], item["project_name"].lower()))[:25],
        "findings": findings[:50],
    }


def _list_projects() -> list[dict[str, Any]]:
    payload = _request("GET", "/projects")
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("projects", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _list_tasks(project_id: int) -> list[dict[str, Any]]:
    payload = _request("GET", f"/projects/{project_id}/tasks")
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("tasks", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _request(method: str, path: str) -> Any:
    headers = {}
    token = _resolve_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(base_url=settings.task_vikunja_url.rstrip("/"), timeout=20.0) as client:
        response = client.request(method, f"{settings.task_vikunja_api_prefix.rstrip('/')}{path}", headers=headers)
        response.raise_for_status()
        return response.json()


def _resolve_token() -> str:
    if settings.task_vikunja_token:
        return settings.task_vikunja_token.strip()
    if settings.task_vikunja_token_file:
        try:
            with open(settings.task_vikunja_token_file, "r", encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError:
            return ""
    return ""


def _task_item(*, task: dict[str, Any], project: dict[str, Any], due_date: datetime | None, done: bool) -> dict[str, Any]:
    project_id = _int_or_none(project.get("id"))
    return {
        "task_id": _int_or_none(task.get("id")),
        "project_id": project_id,
        "project_name": str(project.get("title") or f"Project {project_id}"),
        "title": str(task.get("title") or ""),
        "due_date": due_date.isoformat() if due_date else None,
        "done": done,
    }


def _artifact_refs(item: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if item.get("task_id") is not None:
        refs.append({"type": "task", "id": item["task_id"]})
    if item.get("project_id") is not None:
        refs.append({"type": "project", "id": item["project_id"]})
    return refs


def _task_actor_keys(task: dict[str, Any], project: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for assignee in (task.get("assignees") or []):
        if not isinstance(assignee, dict):
            continue
        value = str(assignee.get("username") or assignee.get("name") or assignee.get("email") or assignee.get("id") or "").strip()
        if value:
            out.append(value)
    if out:
        return sorted(set(out))
    owner = project.get("owner")
    if isinstance(owner, dict):
        value = str(owner.get("username") or owner.get("name") or owner.get("email") or owner.get("id") or "").strip()
        if value:
            return [value]
    return ["unassigned"]


def _looks_blocked(task: dict[str, Any]) -> bool:
    haystack = f"{task.get('title') or ''} {task.get('description') or ''}".lower()
    return any(token in haystack for token in ("blocked", "waiting on", "pending approval", "stuck"))


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None
