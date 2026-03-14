from __future__ import annotations

import difflib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx

from .mcp_client import TaskMcpClient, TaskMcpError
from .schemas import HealthStatus
from .settings import task_settings


@runtime_checkable
class TaskTools(Protocol):
    def healthcheck(self) -> HealthStatus: ...
    def list_lists(self) -> list[dict[str, Any]]: ...
    def create_list(self, title: str, description: str = "") -> dict[str, Any]: ...
    def get_list(self, list_id: int) -> dict[str, Any] | None: ...
    def list_tasks(self, list_id: int) -> list[dict[str, Any]]: ...
    def delete_list(self, list_id: int) -> dict[str, Any]: ...
    def archive_list(self, list_id: int, *, archived: bool = True) -> dict[str, Any]: ...
    def rename_list(self, list_id: int, title: str) -> dict[str, Any]: ...
    def set_list_parent(self, list_id: int, parent_list_id: int) -> dict[str, Any]: ...
    def create_task(
        self,
        list_id: int,
        *,
        title: str,
        description: str = "",
        done: bool = False,
        due_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]: ...
    def update_task(self, task_id: int, *, patch: dict[str, Any]) -> dict[str, Any]: ...
    def get_task(self, task_id: int) -> dict[str, Any] | None: ...
    def delete_task(self, task_id: int) -> dict[str, Any]: ...
    def ensure_list(self, title: str, *, description: str = "") -> dict[str, Any]: ...
    def get_current_user(self) -> dict[str, Any] | None: ...
    def list_teams(self) -> list[dict[str, Any]]: ...
    def create_team(self, name: str) -> dict[str, Any]: ...
    def share_list_with_team(self, list_id: int, team_id: int, permission: int = 0) -> dict[str, Any]: ...
    def list_team_members(self, team_id: int) -> list[dict[str, Any]]: ...
    def list_list_teams(self, list_id: int) -> list[dict[str, Any]]: ...
    def list_labels(self) -> list[dict[str, Any]]: ...
    def create_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]: ...
    def ensure_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]: ...
    def add_label_to_task(self, task_id: int, label_id: int) -> dict[str, Any]: ...
    def set_task_assignees(self, task_id: int, assignee_ids: list[int]) -> dict[str, Any]: ...
    def set_task_progress(self, task_id: int, progress: float) -> dict[str, Any]: ...
    def set_task_color(self, task_id: int, color: str) -> dict[str, Any]: ...
    def set_task_repeat(self, task_id: int, repeat_after_seconds: int) -> dict[str, Any]: ...
    def add_task_relation(self, task_id: int, other_task_id: int, relation_type: str) -> dict[str, Any]: ...
    def move_task(self, task_id: int, project_id: int) -> dict[str, Any]: ...
    def add_task_attachment(self, task_id: int, *, url: str | None = None, filename: str | None = None, bytes_base64: str | None = None) -> dict[str, Any]: ...
    def capabilities(self) -> dict[str, bool]: ...


class UnsupportedMcpOperation(TaskMcpError):
    pass


@dataclass
class RestTaskTools:
    base_url: str = field(default_factory=lambda: task_settings.task_agent_vikunja_url.rstrip("/"))
    api_prefix: str = field(default_factory=lambda: task_settings.task_agent_vikunja_api_prefix.rstrip("/"))
    timeout_seconds: float = field(default_factory=lambda: task_settings.http_timeout_seconds)
    token: str = field(default_factory=lambda: _resolve_token())

    def healthcheck(self) -> HealthStatus:
        try:
            self._request("GET", "/info")
            return HealthStatus(ok=True, backend_reachable=True, tools_discovered=["http.projects", "http.tasks"])
        except Exception as exc:
            return HealthStatus(ok=False, backend_reachable=False, tools_discovered=[], error=str(exc))

    def list_lists(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/projects")
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("projects", "items", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    def create_list(self, title: str, description: str = "") -> dict[str, Any]:
        payload = self._request("PUT", "/projects", json_body={"title": title, "description": description})
        return payload if isinstance(payload, dict) else {"data": payload}

    def get_list(self, list_id: int) -> dict[str, Any] | None:
        payload = self._request("GET", f"/projects/{list_id}")
        return payload if isinstance(payload, dict) else None

    def list_tasks(self, list_id: int) -> list[dict[str, Any]]:
        payload = self._request("GET", f"/projects/{list_id}/tasks")
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("tasks", "items", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    def delete_list(self, list_id: int) -> dict[str, Any]:
        self._request("DELETE", f"/projects/{list_id}")
        return {"id": list_id, "deleted": True}

    def archive_list(self, list_id: int, *, archived: bool = True) -> dict[str, Any]:
        current = self.get_list(list_id) or {}
        body = {
            "title": str(current.get("title") or f"Project {list_id}"),
            "description": str(current.get("description") or ""),
            "is_archived": bool(archived),
        }
        payload = self._request("POST", f"/projects/{list_id}", json_body=body)
        if isinstance(payload, dict):
            return payload
        return {"id": list_id, "is_archived": bool(archived)}

    def rename_list(self, list_id: int, title: str) -> dict[str, Any]:
        current = self.get_list(list_id) or {}
        body = {
            "title": title,
            "description": str(current.get("description") or ""),
        }
        if current.get("is_archived") is not None:
            body["is_archived"] = bool(current.get("is_archived"))
        if current.get("parent_project_id") is not None:
            body["parent_project_id"] = int(current.get("parent_project_id"))
        payload = self._request("POST", f"/projects/{list_id}", json_body=body)
        if isinstance(payload, dict):
            return payload
        return {"id": int(list_id), "title": title}

    def set_list_parent(self, list_id: int, parent_list_id: int) -> dict[str, Any]:
        current = self.get_list(list_id) or {}
        body = {
            "title": str(current.get("title") or f"Project {list_id}"),
            "description": str(current.get("description") or ""),
            "parent_project_id": int(parent_list_id),
        }
        payload = self._request("POST", f"/projects/{list_id}", json_body=body)
        if isinstance(payload, dict):
            return payload
        return {"id": int(list_id), "parent_project_id": int(parent_list_id)}

    def create_task(
        self,
        list_id: int,
        *,
        title: str,
        description: str = "",
        done: bool = False,
        due_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"title": title, "description": description, "done": done}
        if due_date:
            body["due_date"] = due_date
        if start_date:
            body["start_date"] = start_date
        if end_date:
            body["end_date"] = end_date
        if priority is not None:
            body["priority"] = int(priority)
        payload = self._request("PUT", f"/projects/{list_id}/tasks", json_body=body)
        return payload if isinstance(payload, dict) else {"data": payload}

    def update_task(self, task_id: int, *, patch: dict[str, Any]) -> dict[str, Any]:
        payload = self._request("POST", f"/tasks/{task_id}", json_body=patch)
        return payload if isinstance(payload, dict) else {"data": payload}

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        payload = self._request("GET", f"/tasks/{task_id}")
        return payload if isinstance(payload, dict) else None

    def delete_task(self, task_id: int) -> dict[str, Any]:
        self._request("DELETE", f"/tasks/{task_id}")
        return {"id": task_id, "deleted": True}

    def ensure_list(self, title: str, *, description: str = "") -> dict[str, Any]:
        normalized = _normalize(title)
        for item in self.list_lists():
            name = str(item.get("title") or "")
            if _normalize(name) == normalized or _similarity(_normalize(name), normalized) >= 0.92:
                return item
        return self.create_list(title, description=description)

    def get_current_user(self) -> dict[str, Any] | None:
        try:
            payload = self._request("GET", "/user")
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def list_teams(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/teams")
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("teams", "items", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    def create_team(self, name: str) -> dict[str, Any]:
        payload = self._request("PUT", "/teams", json_body={"name": name})
        return payload if isinstance(payload, dict) else {"data": payload}

    def share_list_with_team(self, list_id: int, team_id: int, permission: int = 0) -> dict[str, Any]:
        try:
            payload = self._request("PUT", f"/projects/{list_id}/teams", json_body={"team_id": team_id, "right": permission})
            return payload if isinstance(payload, dict) else {"data": payload}
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 409:
                return {"list_id": list_id, "team_id": team_id, "permission": permission, "already_shared": True}
            raise

    def list_team_members(self, team_id: int) -> list[dict[str, Any]]:
        payload = self._request("GET", f"/teams/{team_id}/members")
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("members", "items", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    def list_list_teams(self, list_id: int) -> list[dict[str, Any]]:
        payload = self._request("GET", f"/projects/{list_id}/teams")
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("teams", "items", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    def list_labels(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/labels")
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("labels", "items", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    def create_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]:
        body = {"title": title}
        if description:
            body["description"] = description
        if hex_color:
            body["hex_color"] = hex_color
        payload = self._request("PUT", "/labels", json_body=body)
        return payload if isinstance(payload, dict) else {"data": payload}

    def ensure_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]:
        normalized = _normalize(title)
        for item in self.list_labels():
            name = str(item.get("title") or "")
            if _normalize(name) == normalized or _similarity(_normalize(name), normalized) >= 0.9:
                return item
        return self.create_label(title, description=description, hex_color=hex_color)

    def add_label_to_task(self, task_id: int, label_id: int) -> dict[str, Any]:
        payload = self._request("PUT", f"/tasks/{task_id}/labels", json_body={"label_id": int(label_id)})
        return payload if isinstance(payload, dict) else {"task_id": task_id, "label_id": label_id, "ok": True}

    def set_task_assignees(self, task_id: int, assignee_ids: list[int]) -> dict[str, Any]:
        patch = {"assignees": [{"id": int(uid)} for uid in assignee_ids]}
        return self.update_task(task_id, patch=patch)

    def set_task_progress(self, task_id: int, progress: float) -> dict[str, Any]:
        safe_progress = max(0.0, min(float(progress), 100.0))
        return self.update_task(task_id, patch={"percent_done": safe_progress})

    def set_task_color(self, task_id: int, color: str) -> dict[str, Any]:
        return self.update_task(task_id, patch={"hex_color": color})

    def set_task_repeat(self, task_id: int, repeat_after_seconds: int) -> dict[str, Any]:
        return self.update_task(task_id, patch={"repeat_after": int(repeat_after_seconds)})

    def add_task_relation(self, task_id: int, other_task_id: int, relation_type: str) -> dict[str, Any]:
        payload = self._request(
            "PUT",
            f"/tasks/{int(task_id)}/relations",
            json_body={"other_task_id": int(other_task_id), "relation_kind": relation_type},
        )
        return payload if isinstance(payload, dict) else {"task_id": int(task_id), "other_task_id": int(other_task_id), "relation_kind": relation_type}

    def move_task(self, task_id: int, project_id: int) -> dict[str, Any]:
        return self.update_task(task_id, patch={"project_id": int(project_id)})

    def add_task_attachment(self, task_id: int, *, url: str | None = None, filename: str | None = None, bytes_base64: str | None = None) -> dict[str, Any]:
        if url:
            payload = self._request("PUT", f"/tasks/{int(task_id)}/attachments", json_body={"url": url, "file_name": filename or "attachment"})
            return payload if isinstance(payload, dict) else {"task_id": int(task_id), "url": url, "ok": True}
        if bytes_base64:
            payload = self._request(
                "PUT",
                f"/tasks/{int(task_id)}/attachments",
                json_body={"file_name": filename or "attachment.bin", "content_base64": bytes_base64},
            )
            return payload if isinstance(payload, dict) else {"task_id": int(task_id), "file_name": filename or "attachment.bin", "ok": True}
        return {"task_id": int(task_id), "ok": False, "error": "no_attachment_source"}

    def capabilities(self) -> dict[str, bool]:
        return {
            "dates": True,
            "priority": True,
            "labels": True,
            "assignees": True,
            "progress": True,
            "color": True,
            "repeat": True,
            "relations": True,
            "attachments": True,
            "move_task": True,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        url = f"{self.base_url}{self.api_prefix}{path}"
        resp = httpx.request(method, url, params=params, json=json_body, headers=headers, timeout=self.timeout_seconds)
        resp.raise_for_status()
        if resp.status_code == 204:
            return {}
        if not resp.content:
            return {}
        return resp.json()


@dataclass
class McpTaskTools:
    client: TaskMcpClient = field(default_factory=TaskMcpClient)
    discovered_tools: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        try:
            self.discovered_tools = set(self.client.discover_tools())
        except Exception:
            self.discovered_tools = set()

    def healthcheck(self) -> HealthStatus:
        try:
            discovered = self.client.discover_tools(timeout_seconds=task_settings.task_agent_mcp_timeout_seconds)
            self.discovered_tools = set(discovered)
            return HealthStatus(ok=True, backend_reachable=True, tools_discovered=[f"mcp.{name}" for name in sorted(self.discovered_tools)])
        except Exception as exc:
            return HealthStatus(ok=False, backend_reachable=False, tools_discovered=[], error=str(exc))

    def list_lists(self) -> list[dict[str, Any]]:
        payload = self._call("list_lists", {})
        return _extract_list(payload, "result")

    def create_list(self, title: str, description: str = "") -> dict[str, Any]:
        payload = self._call("create_list", {"title": title, "description": description})
        return payload if isinstance(payload, dict) else {"title": title}

    def get_list(self, list_id: int) -> dict[str, Any] | None:
        payload = self._call("get_list", {"project_id": int(list_id)})
        return payload if isinstance(payload, dict) else None

    def list_tasks(self, list_id: int) -> list[dict[str, Any]]:
        payload = self._call("list_tasks", {"project_id": int(list_id), "include_completed": True})
        return _extract_list(payload, "tasks")

    def delete_list(self, list_id: int) -> dict[str, Any]:
        payload = self._call("delete_list", {"project_id": int(list_id)})
        if isinstance(payload, dict) and "deleted" in payload:
            return {"id": int(payload["deleted"]), "deleted": True}
        return {"id": int(list_id), "deleted": True}

    def archive_list(self, list_id: int, *, archived: bool = True) -> dict[str, Any]:
        current = self.get_list(list_id) or {}
        body: dict[str, Any] = {"project_id": int(list_id), "is_archived": bool(archived)}
        if current.get("title") is not None:
            body["title"] = str(current.get("title") or "")
        if current.get("description") is not None:
            body["description"] = str(current.get("description") or "")
        if current.get("parent_project_id") is not None:
            body["parent_project_id"] = int(current.get("parent_project_id"))
        payload = self._call("archive_list", body)
        if isinstance(payload, dict):
            return payload
        return {"id": int(list_id), "is_archived": bool(archived)}

    def rename_list(self, list_id: int, title: str) -> dict[str, Any]:
        body = {"project_id": int(list_id), "title": title}
        current = self.get_list(list_id) or {}
        if current.get("description") is not None:
            body["description"] = str(current.get("description") or "")
        payload = self._call("rename_list", body)
        if isinstance(payload, dict):
            return payload
        return {"id": int(list_id), "title": title}

    def set_list_parent(self, list_id: int, parent_list_id: int) -> dict[str, Any]:
        payload = self._call("set_list_parent", {"project_id": int(list_id), "parent_project_id": int(parent_list_id)})
        if isinstance(payload, dict):
            return payload
        return {"id": int(list_id), "parent_project_id": int(parent_list_id)}

    def create_task(
        self,
        list_id: int,
        *,
        title: str,
        description: str = "",
        done: bool = False,
        due_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        payload = self._call("create_task", {"project_id": int(list_id), "title": title, "description": description})
        created = payload if isinstance(payload, dict) else {"title": title, "project_id": int(list_id)}
        task_id = _int_or_none(created.get("id")) if isinstance(created, dict) else None
        patch: dict[str, Any] = {}
        if due_date:
            patch["due_date"] = due_date
        if start_date:
            patch["start_date"] = start_date
        if end_date:
            patch["end_date"] = end_date
        if priority is not None:
            patch["priority"] = int(priority)
        if task_id is not None and patch:
            self.update_task(task_id, patch=patch)
            created.update(patch)
        if done and task_id is not None:
            self._call("complete_task", {"task_id": task_id})
            created["done"] = True
        return created

    def update_task(self, task_id: int, *, patch: dict[str, Any]) -> dict[str, Any]:
        if not patch:
            return {"id": int(task_id)}
        if patch.get("done") is True and set(patch.keys()) <= {"done"}:
            return self._call("complete_task", {"task_id": int(task_id)})
        unsupported = [
            key
            for key in patch.keys()
            if key not in {"title", "description", "due_date", "priority", "start_date", "end_date", "percent_done", "hex_color", "repeat_after", "assignees", "project_id"}
        ]
        if unsupported:
            raise UnsupportedMcpOperation(f"update_task unsupported MCP patch keys: {', '.join(sorted(unsupported))}")
        args = {"task_id": int(task_id)}
        args.update({k: v for k, v in patch.items() if v is not None and k != "assignees"})
        return self._call("update_task", args)

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        payload = self._call("get_task", {"task_id": int(task_id)})
        return payload if isinstance(payload, dict) else None

    def delete_task(self, task_id: int) -> dict[str, Any]:
        payload = self._call("delete_task", {"task_id": int(task_id)})
        if isinstance(payload, dict) and "deleted" in payload:
            return {"id": int(payload["deleted"]), "deleted": True}
        return {"id": int(task_id), "deleted": True}

    def ensure_list(self, title: str, *, description: str = "") -> dict[str, Any]:
        normalized = _normalize(title)
        for item in self.list_lists():
            name = str(item.get("title") or "")
            if _normalize(name) == normalized or _similarity(_normalize(name), normalized) >= 0.92:
                return item
        return self.create_list(title, description=description)

    def get_current_user(self) -> dict[str, Any] | None:
        raise UnsupportedMcpOperation("get_current_user is not available in current Vikunja MCP toolset")

    def list_teams(self) -> list[dict[str, Any]]:
        raise UnsupportedMcpOperation("list_teams is not available in current Vikunja MCP toolset")

    def create_team(self, name: str) -> dict[str, Any]:
        raise UnsupportedMcpOperation("create_team is not available in current Vikunja MCP toolset")

    def share_list_with_team(self, list_id: int, team_id: int, permission: int = 0) -> dict[str, Any]:
        raise UnsupportedMcpOperation("share_list_with_team is not available in current Vikunja MCP toolset")

    def list_team_members(self, team_id: int) -> list[dict[str, Any]]:
        raise UnsupportedMcpOperation("list_team_members is not available in current Vikunja MCP toolset")

    def list_list_teams(self, list_id: int) -> list[dict[str, Any]]:
        raise UnsupportedMcpOperation("list_list_teams is not available in current Vikunja MCP toolset")

    def list_labels(self) -> list[dict[str, Any]]:
        payload = self._call("list_labels", {})
        return _extract_list(payload, "labels")

    def create_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]:
        color = hex_color.strip() or "#9ca3af"
        payload = self._call("create_label", {"title": title, "hex_color": color})
        return payload if isinstance(payload, dict) else {"title": title, "hex_color": color}

    def ensure_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]:
        normalized = _normalize(title)
        for item in self.list_labels():
            name = str(item.get("title") or "")
            if _normalize(name) == normalized or _similarity(_normalize(name), normalized) >= 0.9:
                return item
        return self.create_label(title, description=description, hex_color=hex_color)

    def add_label_to_task(self, task_id: int, label_id: int) -> dict[str, Any]:
        payload = self._call("add_label_to_task", {"task_id": int(task_id), "label_id": int(label_id)})
        return payload if isinstance(payload, dict) else {"task_id": int(task_id), "label_id": int(label_id), "added": True}

    def set_task_assignees(self, task_id: int, assignee_ids: list[int]) -> dict[str, Any]:
        raise UnsupportedMcpOperation("set_task_assignees is not available in current Vikunja MCP toolset")

    def set_task_progress(self, task_id: int, progress: float) -> dict[str, Any]:
        return self.update_task(task_id, patch={"percent_done": max(0.0, min(float(progress), 100.0))})

    def set_task_color(self, task_id: int, color: str) -> dict[str, Any]:
        return self.update_task(task_id, patch={"hex_color": color})

    def set_task_repeat(self, task_id: int, repeat_after_seconds: int) -> dict[str, Any]:
        return self.update_task(task_id, patch={"repeat_after": int(repeat_after_seconds)})

    def add_task_relation(self, task_id: int, other_task_id: int, relation_type: str) -> dict[str, Any]:
        raise UnsupportedMcpOperation("add_task_relation is not available in current Vikunja MCP toolset")

    def move_task(self, task_id: int, project_id: int) -> dict[str, Any]:
        return self.update_task(task_id, patch={"project_id": int(project_id)})

    def add_task_attachment(self, task_id: int, *, url: str | None = None, filename: str | None = None, bytes_base64: str | None = None) -> dict[str, Any]:
        raise UnsupportedMcpOperation("add_task_attachment is not available in current Vikunja MCP toolset")

    def capabilities(self) -> dict[str, bool]:
        available = self.discovered_tools
        return {
            "dates": True,
            "priority": True,
            "labels": "add_label_to_task" in available or "create_label" in available,
            "assignees": False,
            "progress": "update_task" in available,
            "color": "update_task" in available,
            "repeat": "update_task" in available,
            "relations": False,
            "attachments": False,
            "move_task": "update_task" in available,
        }

    def _call(self, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = _resolve_mcp_tool_name(operation, self.discovered_tools)
        if not tool:
            raise UnsupportedMcpOperation(f"MCP tool for operation '{operation}' is not available")
        return self.client.call_tool(tool, arguments)


@dataclass
class FallbackTaskTools:
    primary: TaskTools
    fallback: TaskTools

    def _use(self, fn: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return getattr(self.primary, fn)(*args, **kwargs)
        except Exception:
            return getattr(self.fallback, fn)(*args, **kwargs)

    def healthcheck(self) -> HealthStatus:
        primary = self.primary.healthcheck()
        secondary = self.fallback.healthcheck()
        if primary.ok:
            discovered = list(primary.tools_discovered)
            discovered.append("backend=mcp")
            return HealthStatus(ok=True, backend_reachable=True, tools_discovered=discovered)
        if secondary.ok:
            discovered = list(secondary.tools_discovered)
            discovered.append("backend=rest_fallback")
            return HealthStatus(ok=True, backend_reachable=True, tools_discovered=discovered, error=primary.error)
        return HealthStatus(
            ok=False,
            backend_reachable=False,
            tools_discovered=[],
            error=f"mcp={primary.error or 'unavailable'}; rest={secondary.error or 'unavailable'}",
        )

    def list_lists(self) -> list[dict[str, Any]]:
        return self._use("list_lists")

    def create_list(self, title: str, description: str = "") -> dict[str, Any]:
        return self._use("create_list", title, description)

    def get_list(self, list_id: int) -> dict[str, Any] | None:
        return self._use("get_list", list_id)

    def list_tasks(self, list_id: int) -> list[dict[str, Any]]:
        return self._use("list_tasks", list_id)

    def delete_list(self, list_id: int) -> dict[str, Any]:
        return self._use("delete_list", list_id)

    def archive_list(self, list_id: int, *, archived: bool = True) -> dict[str, Any]:
        return self._use("archive_list", list_id, archived=archived)

    def rename_list(self, list_id: int, title: str) -> dict[str, Any]:
        return self._use("rename_list", list_id, title)

    def set_list_parent(self, list_id: int, parent_list_id: int) -> dict[str, Any]:
        return self._use("set_list_parent", list_id, parent_list_id)

    def create_task(
        self,
        list_id: int,
        *,
        title: str,
        description: str = "",
        done: bool = False,
        due_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        return self._use(
            "create_task",
            list_id,
            title=title,
            description=description,
            done=done,
            due_date=due_date,
            start_date=start_date,
            end_date=end_date,
            priority=priority,
        )

    def update_task(self, task_id: int, *, patch: dict[str, Any]) -> dict[str, Any]:
        return self._use("update_task", task_id, patch=patch)

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        return self._use("get_task", task_id)

    def delete_task(self, task_id: int) -> dict[str, Any]:
        return self._use("delete_task", task_id)

    def ensure_list(self, title: str, *, description: str = "") -> dict[str, Any]:
        return self._use("ensure_list", title, description=description)

    def get_current_user(self) -> dict[str, Any] | None:
        return self._use("get_current_user")

    def list_teams(self) -> list[dict[str, Any]]:
        return self._use("list_teams")

    def create_team(self, name: str) -> dict[str, Any]:
        return self._use("create_team", name)

    def share_list_with_team(self, list_id: int, team_id: int, permission: int = 0) -> dict[str, Any]:
        return self._use("share_list_with_team", list_id, team_id, permission)

    def list_team_members(self, team_id: int) -> list[dict[str, Any]]:
        return self._use("list_team_members", team_id)

    def list_list_teams(self, list_id: int) -> list[dict[str, Any]]:
        return self._use("list_list_teams", list_id)

    def list_labels(self) -> list[dict[str, Any]]:
        return self._use("list_labels")

    def create_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]:
        return self._use("create_label", title, description=description, hex_color=hex_color)

    def ensure_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]:
        return self._use("ensure_label", title, description=description, hex_color=hex_color)

    def add_label_to_task(self, task_id: int, label_id: int) -> dict[str, Any]:
        return self._use("add_label_to_task", task_id, label_id)

    def set_task_assignees(self, task_id: int, assignee_ids: list[int]) -> dict[str, Any]:
        return self._use("set_task_assignees", task_id, assignee_ids)

    def set_task_progress(self, task_id: int, progress: float) -> dict[str, Any]:
        return self._use("set_task_progress", task_id, progress)

    def set_task_color(self, task_id: int, color: str) -> dict[str, Any]:
        return self._use("set_task_color", task_id, color)

    def set_task_repeat(self, task_id: int, repeat_after_seconds: int) -> dict[str, Any]:
        return self._use("set_task_repeat", task_id, repeat_after_seconds)

    def add_task_relation(self, task_id: int, other_task_id: int, relation_type: str) -> dict[str, Any]:
        return self._use("add_task_relation", task_id, other_task_id, relation_type)

    def move_task(self, task_id: int, project_id: int) -> dict[str, Any]:
        return self._use("move_task", task_id, project_id)

    def add_task_attachment(self, task_id: int, *, url: str | None = None, filename: str | None = None, bytes_base64: str | None = None) -> dict[str, Any]:
        return self._use("add_task_attachment", task_id, url=url, filename=filename, bytes_base64=bytes_base64)

    def capabilities(self) -> dict[str, bool]:
        merged = {}
        try:
            merged.update(self.primary.capabilities())
        except Exception:
            pass
        try:
            fallback_caps = self.fallback.capabilities()
            for key, value in fallback_caps.items():
                merged[key] = bool(merged.get(key)) or bool(value)
        except Exception:
            pass
        return merged


def _resolve_mcp_tool_name(operation: str, available: set[str]) -> str | None:
    aliases: dict[str, list[str]] = {
        "list_lists": ["list_projects", "list_all_projects"],
        "create_list": ["create_project", "setup_project"],
        "get_list": ["get_project"],
        "list_tasks": ["list_tasks", "list_all_tasks"],
        "delete_list": ["delete_project"],
        "archive_list": ["update_project"],
        "rename_list": ["update_project"],
        "set_list_parent": ["update_project"],
        "create_task": ["create_task"],
        "update_task": ["update_task"],
        "get_task": ["get_task"],
        "complete_task": ["complete_task"],
        "delete_task": ["delete_task"],
        "list_labels": ["list_labels"],
        "create_label": ["create_label"],
        "add_label_to_task": ["add_label_to_task"],
        "set_task_assignees": ["set_task_assignees", "assign_task"],
        "set_task_progress": ["set_task_progress"],
        "set_task_color": ["set_task_color"],
        "set_task_repeat": ["set_task_repeat"],
        "add_task_relation": ["add_task_relation"],
        "move_task": ["move_task"],
        "add_task_attachment": ["add_task_attachment", "upload_task_attachment"],
    }
    for candidate in aliases.get(operation, []):
        if candidate in available:
            return candidate
    return None


def _extract_list(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        for alt in ("items", "data", "result", "tasks", "labels"):
            value = payload.get(alt)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _resolve_token() -> str:
    if task_settings.task_agent_vikunja_token.strip():
        return task_settings.task_agent_vikunja_token.strip()
    path = task_settings.task_agent_vikunja_token_file.strip()
    if not path:
        return ""
    file_path = Path(os.path.expanduser(path))
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8").strip()


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(a=a, b=b).ratio()


def task_tools() -> TaskTools:
    backend = task_settings.task_agent_tools_backend
    rest = RestTaskTools()
    if backend == "rest":
        return rest
    mcp = McpTaskTools()
    if backend == "mcp":
        return mcp
    return FallbackTaskTools(primary=mcp, fallback=rest)
